import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { api } from "../api";
import type { Cloud, Element } from "../types";
import { groupCameraDistance } from "../columnGroupGeometry";
import { elementBoxLinePositions } from "../structuralFrameGeometry";

interface Props {
  cloud: Cloud | null;
  elements?: Element[];
  groupPositions: Float32Array;
  selectedElement: Element | null;
  selectedElementPositions: Float32Array;
  selectedElementSections: [Float32Array, Float32Array, Float32Array];
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
    color.setHSL(0.12 - 0.1 * t, 0.78, 0.52);
    colors[i * 3] = Math.round(color.r * 255);
    colors[i * 3 + 1] = Math.round(color.g * 255);
    colors[i * 3 + 2] = Math.round(color.b * 255);
  }
  return colors;
}

export default function Viewer3D({ cloud, elements = [], groupPositions, selectedElement, selectedElementPositions, selectedElementSections, pointSize, colorMode, showPlane, section }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const pointsRef = useRef<THREE.Points | null>(null);
  const materialRef = useRef<THREE.PointsMaterial | null>(null);
  const selectedPointsRef = useRef<THREE.Points | null>(null);
  const selectionOutlineRef = useRef<THREE.LineSegments | null>(null);
  const rawRef = useRef<RawGeometry | null>(null);
  const planeRef = useRef<THREE.Mesh | null>(null);
  const groupSphereRef = useRef<THREE.Sphere | null>(null);
  const bimGroupRef = useRef<THREE.Group | null>(null);
  const [showCloud, setShowCloud] = useState(true);
  const [showColumns, setShowColumns] = useState(true);
  const [showBeams, setShowBeams] = useState(true);
  const [showBraces, setShowBraces] = useState(true);
  const [showTrusses, setShowTrusses] = useState(true);
  const [showWalls, setShowWalls] = useState(true);
  const [activePreset, setActivePreset] = useState<string>("all");

  const setPresetAll = () => {
    setActivePreset("all");
    setShowCloud(true);
    setShowColumns(true);
    setShowBeams(true);
    setShowBraces(true);
    setShowTrusses(true);
    setShowWalls(true);
  };

  const setPresetColumnsAndBeams = () => {
    setActivePreset("columns_beams");
    setShowCloud(false);
    setShowColumns(true);
    setShowBeams(true);
    setShowBraces(false);
    setShowTrusses(false);
    setShowWalls(false);
  };

  const setPresetWallsOnly = () => {
    setActivePreset("walls_only");
    setShowCloud(false);
    setShowColumns(false);
    setShowBeams(false);
    setShowBraces(false);
    setShowTrusses(false);
    setShowWalls(true);
  };

  const setPresetTrussesAndBraces = () => {
    setActivePreset("trusses_braces");
    setShowCloud(false);
    setShowColumns(false);
    setShowBeams(false);
    setShowBraces(true);
    setShowTrusses(true);
    setShowWalls(false);
  };

  const setPresetCleanBim = () => {
    setActivePreset("clean_bim");
    setShowCloud(false);
    setShowColumns(true);
    setShowBeams(true);
    setShowBraces(true);
    setShowTrusses(true);
    setShowWalls(true);
  };

  const setPresetCloudOnly = () => {
    setActivePreset("cloud_only");
    setShowCloud(true);
    setShowColumns(false);
    setShowBeams(false);
    setShowBraces(false);
    setShowTrusses(false);
    setShowWalls(false);
  };
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(0);

  function fitSphere(sphere: THREE.Sphere) {
    const camera = cameraRef.current, controls = controlsRef.current;
    if (!camera || !controls) return;
    const radius = Math.max(1, sphere.radius);
    const distance = groupCameraDistance(radius, camera.fov, camera.aspect);
    const direction = camera.position.clone().sub(controls.target).normalize();
    if (direction.lengthSq() === 0) direction.set(1, -1, 0.8).normalize();
    controls.target.copy(sphere.center);
    camera.position.copy(sphere.center).add(direction.multiplyScalar(distance));
    camera.near = Math.max(0.01, radius / 500);
    camera.far = Math.max(radius * 50, (rawRef.current?.radius ?? 0) * 50, distance + radius * 2);
    camera.updateProjectionMatrix();
    controls.update();
  }

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xfaf8f5);
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
    const grid = new THREE.GridHelper(40, 40, 0xc8beb3, 0xe5ddd4);
    grid.rotation.x = Math.PI / 2;
    grid.position.z = -0.001;
    scene.add(grid);
    scene.add(new THREE.AmbientLight(0xffffff, 1.2));
    const bimGroup = new THREE.Group();
    bimGroup.name = "bim-structural-elements";
    scene.add(bimGroup);
    bimGroupRef.current = bimGroup;
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
      if (groupSphereRef.current) fitSphere(groupSphereRef.current);
      else if (rawRef.current) fitSphere(new THREE.Sphere(new THREE.Vector3(), Math.max(1, rawRef.current.radius)));
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
      if (bimGroupRef.current) {
        scene.remove(bimGroupRef.current);
        bimGroupRef.current = null;
      }
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

        fitSphere(groupSphereRef.current ?? new THREE.Sphere(new THREE.Vector3(), Math.max(1, maxRadius)));
      } catch (err: any) {
        if (err?.name !== "AbortError") setError(String(err?.message || err));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [cloud?.id, cloud?.updated_at]);

  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene || !groupPositions.length) return;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(groupPositions, 3));
    const material = new THREE.LineBasicMaterial({ color: 0xb55631, depthTest: false, depthWrite: false });
    const outline = new THREE.LineSegments(geometry, material);
    outline.name = "column-type-group";
    outline.renderOrder = 3;
    scene.add(outline);
    geometry.computeBoundingSphere();
    const sphere = geometry.boundingSphere;
    if (sphere) { groupSphereRef.current = sphere; fitSphere(sphere); }
    return () => {
      if (groupSphereRef.current === sphere) groupSphereRef.current = null;
      scene.remove(outline); geometry.dispose(); material.dispose();
    };
  }, [groupPositions, loaded]);

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
    if (selectedPointsRef.current) {
      scene.remove(selectedPointsRef.current);
      selectedPointsRef.current.geometry.dispose();
      (selectedPointsRef.current.material as THREE.Material).dispose();
      selectedPointsRef.current = null;
    }
    if (selectionOutlineRef.current) {
      scene.remove(selectionOutlineRef.current);
      selectionOutlineRef.current.geometry.dispose();
      (selectionOutlineRef.current.material as THREE.Material).dispose();
      selectionOutlineRef.current = null;
    }
    if (!selectedElement || selectedElementPositions.length === 0) return;

    const pointGeometry = new THREE.BufferGeometry();
    pointGeometry.setAttribute("position", new THREE.BufferAttribute(selectedElementPositions, 3));
    pointGeometry.computeBoundingSphere();
    const pointMaterial = new THREE.PointsMaterial({
      color: 0xffd54a,
      size: Math.max(0.008, (rawRef.current?.radius ?? 1) / 420) * pointSize,
      sizeAttenuation: true,
      depthTest: false,
      transparent: true,
      opacity: 0.96,
    });
    const selectedPoints = new THREE.Points(pointGeometry, pointMaterial);
    selectedPoints.renderOrder = 2;
    selectedPoints.frustumCulled = false;
    scene.add(selectedPoints);
    selectedPointsRef.current = selectedPoints;

    const sectionColors = [0xb55631, 0x9a6819, 0x6b8069];
    const sectionPoints: THREE.Points[] = [];
    selectedElementSections.forEach((positions, index) => {
      if (positions.length === 0) return;
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      const material = new THREE.PointsMaterial({
        color: sectionColors[index],
        size: Math.max(0.01, (rawRef.current?.radius ?? 1) / 350) * pointSize,
        sizeAttenuation: true,
        depthTest: false,
      });
      const slice = new THREE.Points(geometry, material);
      slice.renderOrder = 4 + index;
      slice.frustumCulled = false;
      scene.add(slice);
      sectionPoints.push(slice);
    });

    const origin = cloud?.origin ?? [0, 0, 0];
    const min = selectedElement.bbox.min;
    const max = selectedElement.bbox.max;
    const size = new THREE.Vector3(
      Math.max(0.005, max[0] - min[0]),
      Math.max(0.005, max[1] - min[1]),
      Math.max(0.005, max[2] - min[2]),
    );
    const boxGeometry = new THREE.BoxGeometry(size.x, size.y, size.z);
    const outline = new THREE.LineSegments(
      new THREE.EdgesGeometry(boxGeometry),
      new THREE.LineBasicMaterial({ color: 0xffd54a, depthTest: false, transparent: true, opacity: 0.9 }),
    );
    boxGeometry.dispose();
    outline.position.set(
      (min[0] + max[0]) / 2 - origin[0],
      (min[1] + max[1]) / 2 - origin[1],
      (min[2] + max[2]) / 2 - origin[2],
    );
    outline.renderOrder = 3;
    scene.add(outline);
    selectionOutlineRef.current = outline;
    return () => {
      scene.remove(selectedPoints);
      selectedPoints.geometry.dispose();
      pointMaterial.dispose();
      sectionPoints.forEach((slice) => {
        scene.remove(slice);
        slice.geometry.dispose();
        (slice.material as THREE.Material).dispose();
      });
      if (selectionOutlineRef.current === outline) {
        scene.remove(outline);
        outline.geometry.dispose();
        (outline.material as THREE.Material).dispose();
        selectionOutlineRef.current = null;
      }
      if (selectedPointsRef.current === selectedPoints) selectedPointsRef.current = null;
    };
  }, [selectedElement?.id, selectedElementPositions, selectedElementSections, pointSize, cloud?.id, cloud?.origin]);

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
      color: 0xb55631,
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
  const counts = (elements || []).reduce<Record<string, number>>((acc, el) => {
    acc[el.class_name] = (acc[el.class_name] || 0) + 1;
    return acc;
  }, {});

  useEffect(() => {
    if (pointsRef.current) {
      pointsRef.current.visible = showCloud;
    }
  }, [showCloud]);

  useEffect(() => {
    const bimGroup = bimGroupRef.current;
    if (!bimGroup) return;

    while (bimGroup.children.length > 0) {
      const child = bimGroup.children[0] as THREE.LineSegments;
      bimGroup.remove(child);
      child.geometry?.dispose();
      (child.material as THREE.Material)?.dispose();
    }

    if (!elements || elements.length === 0) return;
    const origin = cloud?.origin || [0, 0, 0];

    const layers: { key: string; color: number; visible: boolean; renderOrder: number }[] = [
      { key: "column", color: 0x38bdf8, visible: showColumns, renderOrder: 10 },
      { key: "beam", color: 0xf59e0b, visible: showBeams, renderOrder: 9 },
      { key: "brace", color: 0xa855f7, visible: showBraces, renderOrder: 8 },
      { key: "truss", color: 0x10b981, visible: showTrusses, renderOrder: 7 },
      { key: "wall", color: 0x94a3b8, visible: showWalls, renderOrder: 6 },
    ];

    for (const layer of layers) {
      if (!layer.visible) continue;
      const positions = elementBoxLinePositions(elements, layer.key, origin);
      if (positions.length === 0) continue;

      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      const material = new THREE.LineBasicMaterial({
        color: layer.color,
        transparent: true,
        opacity: 0.85,
        depthTest: false,
      });
      const lines = new THREE.LineSegments(geometry, material);
      lines.name = `bim-layer-${layer.key}`;
      lines.renderOrder = layer.renderOrder;
      lines.frustumCulled = false;
      bimGroup.add(lines);
    }
  }, [elements, cloud?.origin, showColumns, showBeams, showBraces, showTrusses, showWalls]);


  return (
    <div className="viewer">
      <div ref={hostRef} className="viewer-canvas" />
      <div className="viewer-hud">
        {/* Preset Mode Bar */}
        <div className="viewer-hud-row" style={{ borderBottom: "1px solid rgba(200, 190, 180, 0.4)", paddingBottom: "5px" }}>
          <span style={{ fontWeight: 600, color: "#555", marginRight: "2px" }}>Режимы:</span>
          <button
            type="button"
            className="hud-chip"
            style={{
              cursor: "pointer",
              background: activePreset === "all" ? "#2563eb" : "#f0ebe4",
              color: activePreset === "all" ? "#fff" : "#444",
              border: "1px solid #2563eb",
              borderRadius: "4px",
              padding: "2px 8px",
            }}
            onClick={setPresetAll}
            title="Показать все слои модели"
          >
            🔘 Все слои
          </button>
          <button
            type="button"
            className="hud-chip"
            style={{
              cursor: "pointer",
              background: activePreset === "columns_beams" ? "#0284c7" : "#f0ebe4",
              color: activePreset === "columns_beams" ? "#fff" : "#0284c7",
              border: "1px solid #0284c7",
              borderRadius: "4px",
              padding: "2px 8px",
              fontWeight: activePreset === "columns_beams" ? 700 : 500,
            }}
            onClick={setPresetColumnsAndBeams}
            title="Показать только колонны и балки (основной каркас)"
          >
            🏢+🏗️ Только колонны и балки
          </button>
          <button
            type="button"
            className="hud-chip"
            style={{
              cursor: "pointer",
              background: activePreset === "walls_only" ? "#475569" : "#f0ebe4",
              color: activePreset === "walls_only" ? "#fff" : "#475569",
              border: "1px solid #475569",
              borderRadius: "4px",
              padding: "2px 8px",
              fontWeight: activePreset === "walls_only" ? 700 : 500,
            }}
            onClick={setPresetWallsOnly}
            title="Показать только стены"
          >
            🧱 Только стены
          </button>
          <button
            type="button"
            className="hud-chip"
            style={{
              cursor: "pointer",
              background: activePreset === "trusses_braces" ? "#7c3aed" : "#f0ebe4",
              color: activePreset === "trusses_braces" ? "#fff" : "#7c3aed",
              border: "1px solid #7c3aed",
              borderRadius: "4px",
              padding: "2px 8px",
            }}
            onClick={setPresetTrussesAndBraces}
            title="Показать фермы и связи (система жесткости)"
          >
            📐+⚡ Фермы и связи
          </button>
          <button
            type="button"
            className="hud-chip"
            style={{
              cursor: "pointer",
              background: activePreset === "clean_bim" ? "#059669" : "#f0ebe4",
              color: activePreset === "clean_bim" ? "#fff" : "#059669",
              border: "1px solid #059669",
              borderRadius: "4px",
              padding: "2px 8px",
            }}
            onClick={setPresetCleanBim}
            title="Чистый 3D BIM каркас без точек облака"
          >
            🏛️ Чистый каркас
          </button>
          <button
            type="button"
            className="hud-chip"
            style={{
              cursor: "pointer",
              background: activePreset === "cloud_only" ? "#4b5563" : "#f0ebe4",
              color: activePreset === "cloud_only" ? "#fff" : "#4b5563",
              border: "1px solid #4b5563",
              borderRadius: "4px",
              padding: "2px 8px",
            }}
            onClick={setPresetCloudOnly}
            title="Только исходное облако точек"
          >
            ☁️ Только облако
          </button>
        </div>

        {/* Individual Layer Toggles */}
        <div className="viewer-hud-row">
          <span style={{ fontWeight: 600, color: "#555", marginRight: "2px" }}>Слои:</span>
          {loading && <span>загрузка превью…</span>}
          {!loading && loaded > 0 && (
            <button
              type="button"
              className="hud-chip"
              style={{
                cursor: "pointer",
                background: showCloud ? "#2563eb" : "#f5f2ed",
                color: showCloud ? "#fff" : "#888",
                border: "1px solid #2563eb",
                borderRadius: "4px",
                padding: "2px 8px",
              }}
              onClick={() => { setActivePreset("custom"); setShowCloud(!showCloud); }}
              title="Включить / скрыть облако точек"
            >
              ☁️ Облако ({loaded.toLocaleString()})
            </button>
          )}
          {(counts.column || 0) > 0 && (
            <button
              type="button"
              className="hud-chip"
              style={{
                cursor: "pointer",
                background: showColumns ? "#0284c7" : "#f5f2ed",
                color: showColumns ? "#fff" : "#888",
                border: "1px solid #0284c7",
                borderRadius: "4px",
                padding: "2px 8px",
              }}
              onClick={() => { setActivePreset("custom"); setShowColumns(!showColumns); }}
              title="Показать / скрыть 3D колонны"
            >
              🏢 Колонны ({counts.column})
            </button>
          )}
          {(counts.beam || 0) > 0 && (
            <button
              type="button"
              className="hud-chip"
              style={{
                cursor: "pointer",
                background: showBeams ? "#d97706" : "#f5f2ed",
                color: showBeams ? "#fff" : "#888",
                border: "1px solid #d97706",
                borderRadius: "4px",
                padding: "2px 8px",
              }}
              onClick={() => { setActivePreset("custom"); setShowBeams(!showBeams); }}
              title="Показать / скрыть подкрановые и продольные балки"
            >
              🏗️ Балки ({counts.beam})
            </button>
          )}
          {(counts.brace || 0) > 0 && (
            <button
              type="button"
              className="hud-chip"
              style={{
                cursor: "pointer",
                background: showBraces ? "#7c3aed" : "#f5f2ed",
                color: showBraces ? "#fff" : "#888",
                border: "1px solid #7c3aed",
                borderRadius: "4px",
                padding: "2px 8px",
              }}
              onClick={() => { setActivePreset("custom"); setShowBraces(!showBraces); }}
              title="Показать / скрыть связи"
            >
              ⚡ Связи ({counts.brace})
            </button>
          )}
          {(counts.truss || 0) > 0 && (
            <button
              type="button"
              className="hud-chip"
              style={{
                cursor: "pointer",
                background: showTrusses ? "#059669" : "#f5f2ed",
                color: showTrusses ? "#fff" : "#888",
                border: "1px solid #059669",
                borderRadius: "4px",
                padding: "2px 8px",
              }}
              onClick={() => { setActivePreset("custom"); setShowTrusses(!showTrusses); }}
              title="Показать / скрыть стропильные фермы"
            >
              📐 Фермы ({counts.truss})
            </button>
          )}
          {(counts.wall || 0) > 0 && (
            <button
              type="button"
              className="hud-chip"
              style={{
                cursor: "pointer",
                background: showWalls ? "#475569" : "#f5f2ed",
                color: showWalls ? "#fff" : "#888",
                border: "1px solid #475569",
                borderRadius: "4px",
                padding: "2px 8px",
              }}
              onClick={() => { setActivePreset("custom"); setShowWalls(!showWalls); }}
              title="Показать / скрыть стены"
            >
              🧱 Стены ({counts.wall})
            </button>
          )}
          {cloud?.decimated && <span className="warn">прорежено</span>}
          {groupPositions.length > 0 && <span>контуры группы: {groupPositions.length / 72}</span>}
        </div>
      </div>
      {error && <div className="viewer-error">{error}</div>}
      {!cloud && <div className="viewer-empty">Импортируйте облако точек или загрузите демо-комнату</div>}
    </div>
  );
}
