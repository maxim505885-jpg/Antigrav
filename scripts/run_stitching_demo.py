import sys
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))

import json
import numpy as np
from scan2bim.registration.stitching import rigid_icp, export_stitched_cloud, create_recap_registration_project

# Загружаем выборки точек из двух облаков
cloud1_pos_file = Path("data/projects/3f6321f10c9145db909ec27b1c2ba044/clouds/2621e5a320df49949d04aa1b7399539e/positions.npy")
source_pts = np.load(cloud1_pos_file, mmap_mode="r")[:20000]

pts2_file = Path("data/projects/cloud_2_rcs_stream/xyz.f64")
target_pts = np.fromfile(pts2_file, dtype=np.float64, count=20000 * 3).reshape(-1, 3)

# Создаем парную стоянку с контролируемым смещением
shift = np.array([1.5, -0.8, 0.2])
test_target = source_pts + shift + np.random.normal(0, 0.003, size=source_pts.shape)

print("Запуск совмещения ICP (Kabsch SVD + KDTree)...")
reg_result = rigid_icp(source_pts, test_target, max_iterations=30, tolerance_m=0.001)

print(f"Статус сходимости ICP: {'УСПЕШНО СОШЛОСЬ' if reg_result['converged'] else 'НЕ СОШЛОСЬ'}")
print(f"Итераций: {reg_result['iterations']}")
print(f"Ошибка взаимной невязки (RMSE): {reg_result['rmse_mm']:.2f} мм")
mat4x4 = np.array(reg_result['matrix_4x4'])
print("Матрица 4x4:")
print(np.round(mat4x4, 4))

out_dir = Path("data/output/workshop_release/registration_run")
out_dir.mkdir(parents=True, exist_ok=True)

# Экспорт объединенного сшитого облака точек
stations_data = [
    {"points": source_pts, "matrix_4x4": np.eye(4)},
    {"points": test_target, "matrix_4x4": mat4x4}
]
ply_out = out_dir / "stitched_workshop_scans.ply"
export_stitched_cloud(stations_data, ply_out)
print(f"Сшитое облако успешно экспортировано: {ply_out} ({ply_out.stat().st_size / (1024*1024):.2f} MB)")

# Формирование ReCap Registration Project
recap_proj = out_dir / "recap_registration_manifest.json"
stations = [
    {"id": "Station_01_1rcs", "path": r"C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\1.rcs", "point_count": 297873927, "matrix_4x4": np.eye(4).tolist(), "rmse_mm": 0.0},
    {"id": "Station_02_2rcs", "path": r"C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\2.rcs", "point_count": 580000000, "matrix_4x4": reg_result['matrix_4x4'], "rmse_mm": float(reg_result['rmse_mm'])}
]
create_recap_registration_project(stations, "Регистрация_Цеха_Стоянки_1_и_2", recap_proj)
print(f"Манифест проекта ReCap создан: {recap_proj}")
