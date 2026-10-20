import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { api } from "../api";
import type { Cloud } from "../types";

interface Props {
  cloud: Cloud | null;
  pointSize: number;
  colorMode: "rgb" | "height";
  showPlane: boolean;
  section: { kind: "horizontal" | "vertical"; axis: "x" | "y"; position: number } | null;
}

interface RawGeometry {
  positions: Float32Array;
  colors: Uint8Array | null;
  z: Float32Array;
  radius: number;
}

function heightColors(z: Float32Array): Uint8Array {
  const colors = new Uint8Array(z.length * 3);
  let min = Infinity;
  let max = -Infinity;
  for (let i = 0; i < z.length; i += 1) {
    if (z[i] < min) min = z[i];
    if (z[i] > max) max = z[i];
  }
  const span = Math.max(1e-6, max - min);
  const color = new THREE.Color();
  for (let i = 0; i < z.length; i += 1) {
    const t = (z[i] - min) / span;
    color.setHSL(0.66 - 0.66 * t, 0.8, 0.55);
    colors[i * 3] = Math.round(color.r * 255);
    colors[i * 3 + 1] = Math.round(color.g * 255);
    colors[i * 3 + 2] = Math.round(color.b * 255);
  }
  return colors;
}

export default function Viewer3D({ cloud, pointSize, colorMode, showPlane, section }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const pointsRef = useRef<THREE.Points | null>(null);
  const materialRef = useRef<THREE.PointsMaterial | null>(null);
  const rawRef = useRef<RawGeometry | null>(null);
  const planeRef = useRef<THREE.Mesh | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(0);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b0e13);
    const camera = new THREE.PerspectiveCamera(55, 1, 0.01, 5000);
    camera.up.set(0, 0, 1);
    camera.position.set(9, -11, 8);
    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.domElement.style.display = "block";
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    host.appendChild(renderer.domElement);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.screenSpacePanning = true;
    controls.target.set(0, 0, 0);
    const grid = new THREE.GridHelper(40, 40, 0x30363d, 0x1b2028);
    grid.rotation.x = Math.PI / 2;
    grid.position.z = -0.001;
    scene.add(grid);
    scene.add(new THREE.AmbientLight(0xffffff, 1.2));
    sceneRef.current = scene;
    cameraRef.current = camera;
    rendererRef.current = renderer;
    controlsRef.current = controls;
    // Debug hook: lets support/automation check what the GPU actually drew
    // (renderer.info.render.points) without a screenshot. Read-only usage.
    (window as unknown as Record<string, unknown>).__s2bViewer = { renderer, scene, camera };

    const resize = () => {
      const width = host.clientWidth;
      const height = host.clientHeight;
      if (!width || !height) return;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    resize();

    let frame = 0;
    const animate = () => {
      frame = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    animate();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      controls.dispose();
      renderer.dispose();
      if (renderer.domElement.parentElement === host) host.removeChild(renderer.domElement);
      scene.clear();
      rendererRef.current = null;
      sceneRef.current = null;
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const scene = sceneRef.current;
    if (!scene) return;
    if (pointsRef.current) {
      scene.remove(pointsRef.current);
      pointsRef.current.geometry.dispose();
      materialRef.current?.dispose();
      pointsRef.current = null;
      materialRef.current = null;
    }
    rawRef.current = null;
    setLoaded(0);
    if (!cloud || cloud.status !== "ready") {
      setError(null);
      return () => controller.abort();
    }
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const response = await fetch(api.previewUrl(cloud.id), { signal: controller.signal });
        if (!response.ok) throw new Error(`preview HTTP ${response.status}`);
        const buffer = await response.arrayBuffer();
        const stride = 15;
        const count = Math.floor(buffer.byteLength / stride);
        const view = new DataView(buffer);
        const positions = new Float32Array(count * 3);
        const z = new Float32Array(count);
        const colors = new Uint8Array(count * 3);
        let maxRadius = 0;
        for (let i = 0; i < count; i += 1) {
          const offset = i * stride;
          const x = view.getFloat32(offset, true);
          const y = view.getFloat32(offset + 4, true);
          const zz = view.getFloat32(offset + 8, true);
          positions[i * 3] = x;
          positions[i * 3 + 1] = y;
          positions[i * 3 + 2] = zz;
          z[i] = zz;
          colors[i * 3] = view.getUint8(offset + 12);
          colors[i * 3 + 1] = view.getUint8(offset + 13);
          colors[i * 3 + 2] = view.getUint8(offset + 14);
          maxRadius = Math.max(maxRadius, Math.hypot(x, y, zz));
        }
        rawRef.current = { positions, colors, z, radius: maxRadius };
        setLoaded(count);
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
        geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3, true));
        geometry.computeBoundingSphere();
        const material = new THREE.PointsMaterial({
          size: Math.max(0.004, maxRadius / 600) * pointSize,
          vertexColors: true,
          sizeAttenuation: true,
          transparent: false,
        });
        const points = new THREE.Points(geometry, material);
        points.frustumCulled = false;
        scene.add(points);
        pointsRef.current = points;
        materialRef.current = material;

        const camera = cameraRef.current;
        const controls = controlsRef.current;
        if (camera && controls) {
          const radius = Math.max(1, maxRadius);
          controls.target.set(0, 0, 0);
          camera.position.set(radius * 1.15, -radius * 1.25, radius * 0.85);
          camera.near = Math.max(0.01, radius / 500);
          camera.far = radius * 50;
          camera.updateProjectionMatrix();
          controls.update();
        }
      } catch (err: any) {
        if (err?.name !== "AbortError") setError(String(err?.message || err));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [cloud?.id, cloud?.updated_at]);

  useEffect(() => {
    const material = materialRef.current;
    const raw = rawRef.current;
    const points = pointsRef.current;
    if (!material || !raw || !points) return;
    const useRgb = colorMode === "rgb" && cloud?.has_color;
    const colors = useRgb ? raw.colors! : heightColors(raw.z);
    const attribute = points.geometry.getAttribute("color") as THREE.BufferAttribute;
    attribute.array = colors;
    attribute.needsUpdate = true;
    material.size = Math.max(0.004, raw.radius / 600) * pointSize;
    material.needsUpdate = true;
  }, [colorMode, pointSize, loaded, cloud?.has_color]);

  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;
    if (planeRef.current) {
      scene.remove(planeRef.current);
      planeRef.current.geometry.dispose();
      (planeRef.current.material as THREE.Material).dispose();
      planeRef.current = null;
    }
    if (!showPlane || !section || !cloud?.bbox_min || !cloud.bbox_max || !cloud.origin) return;
    const min = cloud.bbox_min;
    const max = cloud.bbox_max;
    const origin = cloud.origin;
    const dx = max[0] - min[0];
    const dy = max[1] - min[1];
    const dz = max[2] - min[2];
    let width = dx;
    let height = dy;
    let position = new THREE.Vector3(0, 0, section.position - origin[2]);
    let rotation = new THREE.Euler(0, 0, 0);
    if (section.kind === "horizontal") {
      width = dx * 1.02;
      height = dy * 1.02;
      position = new THREE.Vector3(0, 0, section.position - origin[2]);
    } else if (section.axis === "x") {
      width = dy * 1.02;
      height = dz * 1.02;
      position = new THREE.Vector3(section.position - origin[0], 0, 0);
      rotation = new THREE.Euler(0, Math.PI / 2, 0);
    } else {
      width = dx * 1.02;
      height = dz * 1.02;
      position = new THREE.Vector3(0, section.position - origin[1], 0);
      rotation = new THREE.Euler(Math.PI / 2, 0, 0);
    }
    const geometry = new THREE.PlaneGeometry(Math.max(0.01, width), Math.max(0.01, height));
    const material = new THREE.MeshBasicMaterial({
      color: 0x4da3ff,
      transparent: true,
      opacity: 0.16,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.copy(position);
    mesh.rotation.copy(rotation);
    scene.add(mesh);
    planeRef.current = mesh;
  }, [showPlane, section?.kind, section?.axis, section?.position, cloud?.id, cloud?.updated_at]);

  return (
    <div className="viewer">
      <div ref={hostRef} className="viewer-canvas" />
      <div className="viewer-hud">
        {loading && <span>загрузка превью…</span>}
        {!loading && loaded > 0 && <span>{loaded.toLocaleString()} точек</span>}
        {cloud?.decimated && <span className="warn">прорежено</span>}
      </div>
      {error && <div className="viewer-error">{error}</div>}
      {!cloud && <div className="viewer-empty">Импортируйте облако точек или загрузите демо-комнату</div>}
    </div>
  );
}
