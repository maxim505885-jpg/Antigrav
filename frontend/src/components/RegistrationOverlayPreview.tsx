import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { api } from "../api";
import { decodeRegistrationPreviewPositions, transformRegistrationPreviewPositions } from "../registrationPreview";
import type { Cloud, LodManifest } from "../types";

interface Props {
  source: Cloud;
  target: Cloud;
  sourceToTarget: number[][];
}

const MAX_PREVIEW_POINTS = 250_000;

async function loadPreviewPositions(cloud: Cloud, signal: AbortSignal): Promise<Float32Array> {
  const manifest: LodManifest = await api.getLodManifest(cloud.id);
  const level = [...manifest.levels]
    .filter((candidate) => candidate.points_count > 0 && candidate.points_count <= MAX_PREVIEW_POINTS)
    .sort((a, b) => b.points_count - a.points_count)[0]
    ?? [...manifest.levels].filter((candidate) => candidate.points_count > 0).sort((a, b) => a.points_count - b.points_count)[0];
  if (!level) throw new Error(`Для облака «${cloud.name}» нет готового LOD-предпросмотра`);
  const response = await fetch(api.lodBinaryUrl(cloud.id, level.level), { signal });
  if (!response.ok) throw new Error(`Не удалось загрузить LOD облака «${cloud.name}»: HTTP ${response.status}`);
  try {
    return decodeRegistrationPreviewPositions(await response.arrayBuffer(), MAX_PREVIEW_POINTS);
  } catch (error) {
    throw new Error(`Повреждён LOD-пакет облака «${cloud.name}»: ${error instanceof Error ? error.message : String(error)}`);
  }
}

function pointGeometry(positions: Float32Array, color: number, size: number): THREE.Points {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.computeBoundingSphere();
  const material = new THREE.PointsMaterial({ color, size, sizeAttenuation: true, transparent: true, opacity: 0.9, depthWrite: false });
  const points = new THREE.Points(geometry, material);
  points.frustumCulled = false;
  return points;
}

export function RegistrationOverlayPreview({ source, target, sourceToTarget }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState("Загружаю обзорные уровни облаков…");
  const [pointCounts, setPointCounts] = useState<[number, number] | null>(null);
  const transformKey = JSON.stringify(sourceToTarget);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const abort = new AbortController();
    let frame = 0;
    let alive = true;
    let sourcePoints: THREE.Points | null = null;
    let targetPoints: THREE.Points | null = null;
    let grid: THREE.GridHelper | null = null;
    let controls: OrbitControls | null = null;
    let renderer: THREE.WebGLRenderer | null = null;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#101112");
    const camera = new THREE.PerspectiveCamera(50, 1, 0.01, 1_000_000);

    const resize = () => {
      if (!renderer || !host) return;
      const width = Math.max(1, host.clientWidth);
      const height = Math.max(1, host.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };

    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setClearColor("#101112");
      host.appendChild(renderer.domElement);
      controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      resize();
      const observer = new ResizeObserver(resize);
      observer.observe(host);
      const animate = () => {
        if (!alive || !renderer) return;
        controls?.update();
        renderer.render(scene, camera);
        frame = window.requestAnimationFrame(animate);
      };
      frame = window.requestAnimationFrame(animate);

      void Promise.all([
        loadPreviewPositions(source, abort.signal),
        loadPreviewPositions(target, abort.signal),
      ]).then(([sourceLocal, targetLocal]) => {
        if (!alive) return;
        const alignedSource = transformRegistrationPreviewPositions(sourceLocal, JSON.parse(transformKey) as number[][]);
        const sourceBox = new THREE.Box3().setFromArray(alignedSource);
        const targetBox = new THREE.Box3().setFromArray(targetLocal);
        const combined = sourceBox.union(targetBox);
        const center = combined.getCenter(new THREE.Vector3());
        const size = combined.getSize(new THREE.Vector3());
        const radius = Math.max(1, size.length() / 2);
        const pointSize = Math.max(0.012, Math.min(radius / 320, 0.08));
        sourcePoints = pointGeometry(alignedSource, 0xff812e, pointSize);
        targetPoints = pointGeometry(targetLocal, 0xb9bec4, pointSize);
        scene.add(targetPoints, sourcePoints);
        grid = new THREE.GridHelper(Math.max(20, radius * 2), 20, 0x484b4f, 0x292b2e);
        grid.position.set(center.x, combined.min.y, center.z);
        scene.add(grid);
        camera.position.set(center.x + radius * 1.7, center.y + radius * 1.5, center.z + radius * 1.8);
        camera.near = Math.max(0.01, radius / 10_000);
        camera.far = radius * 100;
        camera.updateProjectionMatrix();
        controls?.target.copy(center);
        controls?.update();
        setPointCounts([sourceLocal.length / 3, targetLocal.length / 3]);
        setStatus("Предпросмотр в общей системе координат · это визуальная проверка, не подтверждение точности.");
      }).catch((error: unknown) => {
        if (!alive || (error instanceof Error && error.name === "AbortError")) return;
        setStatus(error instanceof Error ? error.message : String(error));
      });

      return () => {
        alive = false;
        abort.abort();
        window.cancelAnimationFrame(frame);
        observer.disconnect();
        controls?.dispose();
        scene.remove(sourcePoints!, targetPoints!, grid!);
        for (const points of [sourcePoints, targetPoints]) {
          points?.geometry.dispose();
          (points?.material as THREE.Material | undefined)?.dispose();
        }
        grid?.geometry.dispose();
        (grid?.material as THREE.Material | undefined)?.dispose();
        renderer?.dispose();
        renderer?.domElement.remove();
      };
    } catch (error) {
      setStatus(error instanceof Error ? `3D-предпросмотр недоступен: ${error.message}` : "3D-предпросмотр недоступен");
      return () => {
        alive = false;
        abort.abort();
        window.cancelAnimationFrame(frame);
        controls?.dispose();
        renderer?.dispose();
        renderer?.domElement.remove();
      };
    }
  }, [source.id, target.id, transformKey]);

  return <div className="registration-overlay-preview" aria-label="Предпросмотр совместного облака">
    <div ref={hostRef} className="registration-overlay-canvas" />
    <div className="registration-overlay-caption" role="status" aria-live="polite">
      <span><i className="overlay-source-swatch" /> A · {source.name}</span>
      <span><i className="overlay-target-swatch" /> B · {target.name}</span>
      <strong>{pointCounts ? `${pointCounts[0].toLocaleString("ru-RU")} + ${pointCounts[1].toLocaleString("ru-RU")} точек LOD` : status}</strong>
      {pointCounts && <small>{status}</small>}
    </div>
  </div>;
}
