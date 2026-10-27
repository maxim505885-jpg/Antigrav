"""Experimental heuristic pipeline for structural point-cloud registration.

This module combines hand-built BEV/FFT candidate search, local point-to-plane
ICP and a Russian diagnostic log. It is not a neural network, does not run pose
graph optimization as part of ``auto_stitch``, and does not establish accuracy
without independent control points. Its outputs remain candidates for review.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import minimize
from scipy.signal import fftconvolve
from scipy.spatial import cKDTree


def make_rot_z(angle_rad: float) -> np.ndarray:
    """Создать 3x3 матрицу вращения вокруг вертикальной оси Z."""
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    return np.array([
        [c, -s, 0.0],
        [s,  c, 0.0],
        [0.0, 0.0, 1.0],
    ], dtype=np.float64)


def _registration_xyz(cloud: np.ndarray, name: str) -> np.ndarray:
    """Return validated XYZ coordinates, ignoring optional non-coordinate columns."""
    points = np.asarray(cloud, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] < 3:
        raise ValueError(f"{name} must be a 2D array with at least 3 columns (XYZ)")
    xyz = points[:, :3]
    if len(xyz) < 3:
        raise ValueError(f"{name} must contain at least 3 finite XYZ points")
    if not np.isfinite(xyz).all():
        raise ValueError(f"{name} must contain only finite XYZ coordinates")
    return xyz


def extract_bev_structural_features(
    cloud: np.ndarray, cell_size_m: float = 0.20
) -> Dict[str, Any]:
    """Извлечение многоканального 2D BEV-тензора структурных признаков здания."""
    pts = np.asarray(cloud, dtype=np.float32)
    min_xy = np.min(pts[:, :2], axis=0)
    max_xy = np.max(pts[:, :2], axis=0)
    span_xy = np.maximum(max_xy - min_xy, 1.0)

    grid_w = int(np.ceil(span_xy[0] / cell_size_m)) + 1
    grid_h = int(np.ceil(span_xy[1] / cell_size_m)) + 1

    ix = np.clip(((pts[:, 0] - min_xy[0]) / cell_size_m).astype(np.int32), 0, grid_w - 1)
    iy = np.clip(((pts[:, 1] - min_xy[1]) / cell_size_m).astype(np.int32), 0, grid_h - 1)
    flat_idx = iy * grid_w + ix

    # Канал 0: Плотность точек
    density = np.bincount(flat_idx, minlength=grid_w * grid_h).reshape((grid_h, grid_w)).astype(np.float32)
    d_max = np.max(density)
    if d_max > 0:
        density /= d_max

    # Канал 1: Вертикальный перепад высот (колонны, стены)
    z = pts[:, 2]
    max_z = np.full(grid_w * grid_h, -1e9, dtype=np.float32)
    min_z = np.full(grid_w * grid_h, 1e9, dtype=np.float32)
    np.maximum.at(max_z, flat_idx, z)
    np.minimum.at(min_z, flat_idx, z)
    h_span = np.maximum(0.0, max_z - min_z)
    h_span[max_z <= -1e8] = 0.0
    h_span = h_span.reshape((grid_h, grid_w))
    h_max = np.max(h_span)
    if h_max > 0:
        h_span /= h_max

    # Канал 2: Бинарная занятость пространства
    occupancy = (density > 0).astype(np.float32)

    tensor = np.stack([density, h_span, occupancy], axis=0)
    return {
        "tensor": tensor,
        "origin_xy": (float(min_xy[0]), float(min_xy[1])),
        "resolution": float(cell_size_m),
    }


def neural_coarse_match(
    source_cloud: np.ndarray, target_cloud: np.ndarray
) -> Dict[str, Any]:
    """Глобальное сопоставление стоянок через круговую 2D BEV-корреляцию и 3D-проверку."""
    src = _registration_xyz(source_cloud, "source_cloud")
    tgt = _registration_xyz(target_cloud, "target_cloud")

    # Робастное отсечение крайних выбросов
    s_min = np.percentile(src[:, :2], 1.0, axis=0)
    s_max = np.percentile(src[:, :2], 99.0, axis=0)
    s_mask = (
        (src[:, 0] >= s_min[0]) & (src[:, 0] <= s_max[0]) &
        (src[:, 1] >= s_min[1]) & (src[:, 1] <= s_max[1])
    )
    s_pts = src[s_mask]

    res = 0.4
    gw_s = int((s_max[0] - s_min[0]) / res) + 1
    gh_s = int((s_max[1] - s_min[1]) / res) + 1
    ix_s = np.clip(((s_pts[:, 0] - s_min[0]) / res).astype(np.int32), 0, gw_s - 1)
    iy_s = np.clip(((s_pts[:, 1] - s_min[1]) / res).astype(np.int32), 0, gh_s - 1)
    grid_s = np.bincount(iy_s * gw_s + ix_s, minlength=gw_s * gh_s).reshape((gh_s, gw_s)).astype(np.float32)
    grid_s = np.clip(grid_s, 0, 20.0)

    c_tgt = np.mean(tgt[:, :2], axis=0)
    tgt_centered = tgt[:, :2] - c_tgt

    tree_tgt = cKDTree(tgt[::max(1, len(tgt) // 3000)])
    sub_src = s_pts[::max(1, len(s_pts) // 1000)]
    tz = float(np.median(s_pts[:, 2]) - np.median(tgt[:, 2]))

    def compute_fft_shift(deg_val: float) -> Tuple[float, np.ndarray]:
        rad = math.radians(deg_val)
        cr, sr = math.cos(rad), math.sin(rad)
        R2 = np.array([[cr, -sr], [sr, cr]])
        tgt_rot = tgt_centered @ R2.T

        t_min = np.min(tgt_rot, axis=0)
        t_max = np.max(tgt_rot, axis=0)
        gw_t = int((t_max[0] - t_min[0]) / res) + 1
        gh_t = int((t_max[1] - t_min[1]) / res) + 1
        ix_t = np.clip(((tgt_rot[:, 0] - t_min[0]) / res).astype(np.int32), 0, gw_t - 1)
        iy_t = np.clip(((tgt_rot[:, 1] - t_min[1]) / res).astype(np.int32), 0, gh_t - 1)
        grid_t = np.bincount(iy_t * gw_t + ix_t, minlength=gw_t * gh_t).reshape((gh_t, gw_t)).astype(np.float32)
        grid_t = np.clip(grid_t, 0, 20.0)

        corr = fftconvolve(grid_s, grid_t[::-1, ::-1], mode="full")
        idx = np.unravel_index(np.argmax(corr), corr.shape)
        shift_y_pix = idx[0] - (gh_t - 1)
        shift_x_pix = idx[1] - (gw_t - 1)
        diff_xy = np.array([
            shift_x_pix * res + s_min[0] - t_min[0],
            shift_y_pix * res + s_min[1] - t_min[1],
        ])
        est_t2d = diff_xy - R2 @ c_tgt
        peak = float(np.max(corr))
        return peak, est_t2d

    candidates = []
    for deg in np.linspace(0, 360, 90, endpoint=False):
        peak, est_t2d = compute_fft_shift(deg)
        candidates.append((peak, deg, est_t2d))

    candidates.sort(key=lambda c: c[0], reverse=True)

    best_score = float("inf")
    best_deg = 0.0
    best_t = np.zeros(3)
    best_R = np.eye(3)

    for peak, base_deg, _ in candidates[:8]:
        for delta in np.linspace(-3.0, 3.0, 7):
            cur_deg = float((base_deg + delta) % 360.0)
            _, est_t2d = compute_fft_shift(cur_deg)
            rad = math.radians(cur_deg)
            R3 = make_rot_z(rad)
            t3 = np.array([est_t2d[0], est_t2d[1], tz])

            aligned = (R3.T @ (sub_src - t3).T).T
            dists, _ = tree_tgt.query(aligned, k=1)
            score = float(np.percentile(dists, 80))
            if score < best_score:
                best_score = score
                best_deg = cur_deg
                best_t = t3
                best_R = R3

    # Тонкая доводка грубого угла и смещения
    def loss(p):
        d_deg, tx, ty = p
        r_mat = make_rot_z(math.radians(d_deg))
        t_vec = np.array([tx, ty, best_t[2]])
        al = (r_mat.T @ (sub_src - t_vec).T).T
        d, _ = tree_tgt.query(al, k=1)
        return float(np.mean(np.clip(d, 0.0, 2.0)))

    opt = minimize(
        loss, [best_deg, best_t[0], best_t[1]], method="Powell",
        options={"maxiter": 8, "ftol": 1e-3}
    )
    final_deg, final_tx, final_ty = opt.x
    final_R = make_rot_z(math.radians(final_deg))
    final_t = np.array([final_tx, final_ty, best_t[2]])

    return {
        "confidence": None,
        "confidence_status": "not_calibrated",
        "coarse_residual_p80_m": float(best_score),
        "rotation": final_R,
        "translation": final_t,
        "angle_deg": float(final_deg),
    }


def point_to_plane_icp(
    source: np.ndarray,
    target: np.ndarray,
    initial_t4x4: Optional[np.ndarray] = None,
    max_iterations: int = 25,
    tolerance_m: float = 1e-4,
) -> Dict[str, Any]:
    """Run local point-to-plane ICP and report whether it had enough support to fit."""
    src = _registration_xyz(source, "source")
    tgt = _registration_xyz(target, "target")
    if len(src) < 30:
        raise ValueError("source must contain at least 30 XYZ points for ICP correspondences")
    if len(tgt) < 15:
        raise ValueError("target must contain at least 15 XYZ points for normal estimation")

    # Оценка нормалей по целевому облаку
    tgt_sub = tgt[::max(1, len(tgt) // 4000)]
    tree_tgt = cKDTree(tgt_sub)
    _, idxs = tree_tgt.query(tgt_sub, k=15)
    normals = np.zeros_like(tgt_sub)
    for i, idx in enumerate(idxs):
        pts = tgt_sub[idx]
        cov = np.cov(pts.T)
        eigvals, eigvecs = np.linalg.eigh(cov)
        n = eigvecs[:, 0]
        normals[i] = n / (np.linalg.norm(n) + 1e-12)

    src_sub = src[::max(1, len(src) // 4000)]

    if initial_t4x4 is not None:
        curr_R = np.array(initial_t4x4[:3, :3], dtype=np.float64)
        curr_t = np.array(initial_t4x4[:3, 3], dtype=np.float64)
    else:
        curr_R = np.eye(3, dtype=np.float64)
        curr_t = np.zeros(3, dtype=np.float64)

    converged = False
    final_rmse: Optional[float] = None
    correspondence_count = 0

    for it in range(max_iterations):
        p_prime = (curr_R @ src_sub.T).T + curr_t
        dists, q_idxs = tree_tgt.query(p_prime, k=1)
        valid = dists < 0.6
        if np.sum(valid) < 30:
            break

        p = p_prime[valid]
        q = tgt_sub[q_idxs[valid]]
        n = normals[q_idxs[valid]]

        r = np.sum((p - q) * n, axis=1)
        correspondence_count = int(np.sum(valid))
        pxn = np.cross(p, n)
        A = np.hstack([pxn, n])
        b = -r

        xi, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
        w = xi[:3]
        dt = xi[3:]

        theta = float(np.linalg.norm(w))
        if theta > 1e-12:
            k = w / theta
            K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
            dR = np.eye(3) + math.sin(theta) * K + (1.0 - math.cos(theta)) * (K @ K)
        else:
            dR = np.eye(3)

        curr_R = dR @ curr_R
        curr_t = dR @ curr_t + dt

        final_rmse = float(np.sqrt(np.mean(r ** 2)))
        if np.linalg.norm(dt) < tolerance_m and theta < 1e-4:
            converged = True
            break

    T4 = np.eye(4, dtype=np.float64)
    T4[:3, :3] = curr_R
    T4[:3, 3] = curr_t

    return {
        "converged": bool(converged),
        "fit_status": "fit" if final_rmse is not None else "insufficient_correspondences",
        "correspondence_count": correspondence_count,
        "rmse_mm": float(final_rmse * 1000.0) if final_rmse is not None else None,
        "matrix_4x4": T4,
    }


def pose_graph_optimize(
    station_count: int, edges: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Геодезическое уравнивание сети стоянок (Pose Graph Optimization)."""
    if station_count <= 1:
        return {
            "poses": [np.eye(4).tolist()],
            "residual_norm_before": 0.0,
            "residual_norm_after": 0.0,
        }

    # Станция 0 жестко закреплена как базис (0, 0, 0)
    # Формируем систему линейных уравнений для t_1 ... t_{N-1}
    num_unknowns = station_count - 1
    A_rows = []
    b_rows = []

    res_before_sq = 0.0

    for edge in edges:
        i = edge["from"]
        j = edge["to"]
        t_meas = np.array(edge["t4x4"], dtype=np.float64)[:3, 3]
        w = float(edge.get("weight", 1.0))

        # Residual before (assuming initial identity)
        res_before_sq += float(np.sum(t_meas ** 2))

        row = np.zeros(num_unknowns, dtype=np.float64)
        if j > 0:
            row[j - 1] += 1.0
        if i > 0:
            row[i - 1] -= 1.0

        A_rows.append(row * w)
        b_rows.append(t_meas * w)

    A = np.array(A_rows, dtype=np.float64)
    B = np.array(b_rows, dtype=np.float64)

    sol, _, _, _ = np.linalg.lstsq(A, B, rcond=None)

    poses = [np.eye(4, dtype=np.float64)]
    for idx in range(num_unknowns):
        P = np.eye(4, dtype=np.float64)
        P[:3, 3] = sol[idx]
        poses.append(P)

    residuals = A @ sol - B
    residual_norm_after = float(np.mean(np.linalg.norm(residuals, axis=1)))
    residual_norm_before = float(np.sqrt(res_before_sq))

    return {
        "poses": [p.tolist() for p in poses],
        "residual_norm_before": residual_norm_before,
        "residual_norm_after": residual_norm_after,
    }


@dataclasses.dataclass
class RegistrationStation:
    """Стоянка лазерного сканирования."""
    id: str
    points: np.ndarray
    name: str = ""
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)


class NeuralRegistrationAgent:
    """Автономный агент сшивки облаков точек с пошаговым рассуждением."""

    def __init__(self, name: str = "TrimblePerspectiveAgent"):
        self.name = name

    def auto_stitch(self, stations: List[RegistrationStation]) -> Dict[str, Any]:
        """Автоматическая сшивка облаков точек с формированием отчета."""
        reasoning_log: List[str] = []

        if len(stations) < 2:
            return {
                "status": "error",
                "converged": False,
                "rmse_mm": 0.0,
                "overlap_ratio": 0.0,
                "reasoning_log": ["Для сшивки требуется как минимум 2 стоянки сканирования."],
                "station_poses": [],
            }

        st_base = stations[0]
        st_moving = stations[1]

        reasoning_log.append(
            f"1. Анализ геометрии: вычисление структурных BEV-дескрипторов для '{st_base.name}' "
            f"({len(st_base.points)} точек) и '{st_moving.name}' ({len(st_moving.points)} точек)."
        )

        bev1 = extract_bev_structural_features(st_base.points)
        bev2 = extract_bev_structural_features(st_moving.points)

        reasoning_log.append(
            "2. Глобальное сопоставление стоянок: поиск взаимного рыскания (yaw dZ) и "
            "горизонтального сдвига (dX, dY) в диапазоне 0-360°."
        )
        coarse = neural_coarse_match(st_moving.points, st_base.points)
        rot = coarse["rotation"]
        trans = coarse["translation"]

        # Матрица приведения moving в систему base: target = R^T @ (source - t)
        inv_R = rot.T
        inv_t = -inv_R @ trans
        init_t4x4 = np.eye(4, dtype=np.float64)
        init_t4x4[:3, :3] = inv_R
        init_t4x4[:3, 3] = inv_t

        reasoning_log.append(
            f"3. Локальная доводка Point-to-Plane ICP с оценкой нормалей поверхностей "
            f"(угол грубой ориентации: {coarse['angle_deg']:.1f}°)."
        )
        icp_res = point_to_plane_icp(
            st_moving.points, st_base.points, initial_t4x4=init_t4x4, max_iterations=30
        )

        fit_detail = (
            f"fit-невязка составляет {icp_res['rmse_mm']:.2f} мм"
            if icp_res["rmse_mm"] is not None
            else "достаточных пар соответствий нет; fit-невязка не вычислена"
        )
        reasoning_log.append(
            f"4. Проверка локальной сходимости ICP: "
            f"сходимость ICP: {'да' if icp_res['converged'] else 'нет'}, "
            f"{fit_detail}; это не независимая точность."
        )

        # Вычисление коэффициента перекрытия (overlap ratio)
        aligned_m = (icp_res["matrix_4x4"][:3, :3] @ st_moving.points[::5].T).T + icp_res["matrix_4x4"][:3, 3]
        tree_base = cKDTree(st_base.points[::5])
        dists, _ = tree_base.query(aligned_m, k=1)
        overlap_ratio = float(np.mean(dists < 0.35))

        reasoning_log.append(
            f"5. Черновое преобразование рассчитано; выборочная доля перекрытия "
            f"{overlap_ratio * 100:.1f}%. Соответствие нормативам не оценивалось: "
            f"независимые контрольные точки отсутствуют."
        )

        return {
            "status": "candidate",
            "converged": bool(icp_res["converged"]),
            "rmse_mm": icp_res["rmse_mm"],
            "overlap_ratio": float(overlap_ratio),
            "accuracy_status": "not_measured",
            "independent_control_checked": False,
            "reasoning_log": reasoning_log,
            "station_poses": [np.eye(4).tolist(), icp_res["matrix_4x4"].tolist()],
        }
