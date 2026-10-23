import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { api } from "../api";
import type { Cloud, Element, LodManifest } from "../types";
import { groupCameraDistance } from "../columnGroupGeometry";
import { selectLodLevel } from "../lodLevel";
import { RenderFpsSampler } from "../renderFps";
import { elementBoxLinePositions } from "../structuralFrameGeometry";
import { computeStructuralGridGeometry } from "../structuralGrid3D";
import { classLabel } from "../types";
import { LimitBoxDock, type LimitBoxRange } from "./LimitBoxDock";
import { Measure3DDock, type MeasureResult } from "./Measure3DDock";

interface Props {
  cloud: Cloud | null;
  elements?: Element[];
  groupPositions: Float32Array;
  selectedElement: Element | null;
  selectedElementPositions: Float32Array;
  selectedElementSections: [Float32Array, Float32Array, Float32Array];
  pointSize: number;
  colorMode: "rgb" | "height" | "intensity" | "normals" | "error";
  enableEDL?: boolean;
  showPlane: boolean;
  section: { kind: "horizontal" | "vertical"; axis: "x" | "y"; position: number } | null;
  hideInternalHud?: boolean;
  limitBoxActive?: boolean;
  onToggleLimitBox?: (active: boolean) => void;
  measureModeActive?: boolean;
  onToggleMeasureMode?: (active: boolean) => void;
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

export default function Viewer3D({
  cloud,
  elements = [],
  groupPositions,
  selectedElement,
  selectedElementPositions,
  selectedElementSections,
  pointSize,
  colorMode,
  showPlane,
  section,
  hideInternalHud,
  limitBoxActive,
  onToggleLimitBox,
  measureModeActive,
  onToggleMeasureMode,
}: Props) {
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
  const gridGroupRef = useRef<THREE.Group | null>(null);
  const [showGrid, setShowGrid] = useState(false);
  const [showCloud, setShowCloud] = useState(true);
  const [showColumns, setShowColumns] = useState(true);
  const [showBeams, setShowBeams] = useState(true);
  const [showBraces, setShowBraces] = useState(true);
  const [showTrusses, setShowTrusses] = useState(true);
  const [showWalls, setShowWalls] = useState(true);
  const [showStairs, setShowStairs] = useState(true);
  const [showOpenings, setShowOpenings] = useState(true);
  const [showPipes, setShowPipes] = useState(true);
  const [activePreset, setActivePreset] = useState<string>("all");

  // ReCap Limit Box state
  const [showLimitBox, setShowLimitBox] = useState(false);
  const isLimitBoxOpen = limitBoxActive !== undefined ? limitBoxActive : showLimitBox;
  const [limitBox, setLimitBox] = useState<LimitBoxRange>({
    minX: -50,
    maxX: 50,
    minY: -50,
    maxY: 50,
    minZ: -2,
    maxZ: 25,
    invert: false,
  });
  const limitBoxHelperRef = useRef<THREE.Box3Helper | null>(null);
  const activeClippingPlanesRef = useRef<THREE.Plane[]>([]);

  // ReCap 3D Laser Measurement state
  const [measureMode, setMeasureMode] = useState(false);
  const isMeasureActive = measureModeActive !== undefined ? measureModeActive : measureMode;
  const measureModeRef = useRef(false);
  measureModeRef.current = isMeasureActive;
  const [measurePoints, setMeasurePoints] = useState<THREE.Vector3[]>([]);
  const measurePointsRef = useRef<THREE.Vector3[]>([]);
  measurePointsRef.current = measurePoints;
  const [measureResult, setMeasureResult] = useState<MeasureResult | null>(null);
  const measureGroupRef = useRef<THREE.Group | null>(null);

  const handleLimitBoxPreset = (preset: "all" | "floor" | "crane" | "roof") => {
    const originZ = cloud?.origin ? cloud.origin[2] : 0;
    if (preset === "all") {
      if (cloud?.bbox_min && cloud?.bbox_max && cloud.origin) {
        setLimitBox({
          minX: cloud.bbox_min[0] - cloud.origin[0] - 1.0,
          maxX: cloud.bbox_max[0] - cloud.origin[0] + 1.0,
          minY: cloud.bbox_min[1] - cloud.origin[1] - 1.0,
          maxY: cloud.bbox_max[1] - cloud.origin[1] + 1.0,
          minZ: cloud.bbox_min[2] - cloud.origin[2] - 0.5,
          maxZ: cloud.bbox_max[2] - cloud.origin[2] + 0.5,
          invert: false,
        });
      } else {
        setLimitBox((prev) => ({ ...prev, minZ: -5, maxZ: 30, invert: false }));
      }
    } else if (preset === "floor") {
      setLimitBox((prev) => ({ ...prev, minZ: -originZ, maxZ: 2.0 - originZ, invert: false }));
    } else if (preset === "crane") {
      setLimitBox((prev) => ({ ...prev, minZ: 5.0 - originZ, maxZ: 9.0 - originZ, invert: false }));
    } else if (preset === "roof") {
      setLimitBox((prev) => ({ ...prev, minZ: 9.0 - originZ, maxZ: 18.0 - originZ, invert: false }));
    }
  };

  const handleClearMeasurement = () => {
    setMeasurePoints([]);
    setMeasureResult(null);
    const grp = measureGroupRef.current;
    if (!grp) return;
    while (grp.children.length > 0) {
      const obj = grp.children[0];
      grp.remove(obj);
      if ((obj as any).geometry) (obj as any).geometry.dispose();
      if ((obj as any).material) (obj as any).material.dispose();
    }
  };

  const updateMeasureVisuals = (pts: THREE.Vector3[]) => {
    const grp = measureGroupRef.current;
    if (!grp) return;
    while (grp.children.length > 0) {
      const obj = grp.children[0];
      grp.remove(obj);
      if ((obj as any).geometry) (obj as any).geometry.dispose();
      if ((obj as any).material) (obj as any).material.dispose();
    }
    pts.forEach((pt) => {
      const sphereGeo = new THREE.SphereGeometry(0.12, 16, 16);
      const sphereMat = new THREE.MeshBasicMaterial({ color: 0x00f0ff, depthTest: false, transparent: true, opacity: 0.95 });
      const mesh = new THREE.Mesh(sphereGeo, sphereMat);
      mesh.position.copy(pt);
      mesh.renderOrder = 9999;
      grp.add(mesh);
    });
    if (pts.length === 2) {
      const lineGeo = new THREE.BufferGeometry().setFromPoints(pts);
      const lineMat = new THREE.LineBasicMaterial({ color: 0xffd54a, linewidth: 2, depthTest: false, transparent: true, opacity: 0.95 });
      const line = new THREE.Line(lineGeo, lineMat);
      line.renderOrder = 9998;
      grp.add(line);
    }
  };

  const setPresetAll = () => {
    setActivePreset("all");
    setShowGrid(true);
    setShowCloud(true);
    setShowColumns(true);
    setShowBeams(true);
    setShowBraces(true);
    setShowTrusses(true);
    setShowWalls(true);
    setShowStairs(true);
    setShowOpenings(true);
    setShowPipes(true);
  };

  const setPresetColumnsAndBeams = () => {
    setActivePreset("columns_beams");
    setShowGrid(true);
    setShowCloud(false);
    setShowColumns(true);
    setShowBeams(true);
    setShowBraces(false);
    setShowTrusses(false);
    setShowWalls(false);
    setShowStairs(false);
    setShowOpenings(false);
    setShowPipes(false);
  };

  const setPresetWallsOnly = () => {
    setActivePreset("walls_only");
    setShowCloud(false);
    setShowColumns(false);
    setShowBeams(false);
    setShowBraces(false);
    setShowTrusses(false);
    setShowWalls(true);
    setShowStairs(false);
    setShowOpenings(true);
  };

  const setPresetTrussesAndBraces = () => {
    setActivePreset("trusses_braces");
    setShowCloud(false);
    setShowColumns(false);
    setShowBeams(false);
    setShowBraces(true);
    setShowTrusses(true);
    setShowWalls(false);
    setShowStairs(false);
    setShowOpenings(false);
  };

  const setPresetCleanBim = () => {
    setActivePreset("clean_bim");
    setShowGrid(true);
    setShowCloud(false);
    setShowColumns(true);
    setShowBeams(true);
    setShowBraces(true);
    setShowTrusses(true);
    setShowWalls(true);
    setShowStairs(true);
    setShowOpenings(true);
  };

  const setPresetCloudOnly = () => {
    setActivePreset("cloud_only");
    setShowGrid(false);
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
  const [fps, setFps] = useState<number | null>(null);

  function fitSphere(sphere: THREE.Sphere) {
    const camera = cameraRef.current, controls = controlsRef.current;
    if (!camera || !controls) return;
    const radius = Math.max(1, sphere.radius);
    const aspect = Math.max(0.1, camera.aspect || 1);
    const distance = groupCameraDistance(radius, camera.fov, aspect);
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
    scene.background = new THREE.Color(0x0a0e13);
    const camera = new THREE.PerspectiveCamera(55, 1, 0.01, 5000);
    camera.up.set(0, 0, 1);
    camera.position.set(9, -11, 8);
    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    renderer.localClippingEnabled = true;
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
    const grid = new THREE.GridHelper(80, 80, 0xff812e, 0x223040);
    grid.rotation.x = Math.PI / 2;
    grid.position.z = -0.001;
    scene.add(grid);
    scene.add(new THREE.AmbientLight(0xffffff, 1.2));
    const bimGroup = new THREE.Group();
    bimGroup.name = "bim-structural-elements";
    scene.add(bimGroup);
    bimGroupRef.current = bimGroup;

    const measureGroup = new THREE.Group();
    measureGroup.name = "recap-measurements";
    scene.add(measureGroup);
    measureGroupRef.current = measureGroup;
    sceneRef.current = scene;
    cameraRef.current = camera;
    rendererRef.current = renderer;
    controlsRef.current = controls;
    // Debug hook: lets support/automation check what the GPU actually drew
    // (renderer.info.render.points) without a screenshot. Read-only usage.
    (window as unknown as Record<string, unknown>).__s2bViewer = { renderer, scene, camera };

    let startX = 0;
    let startY = 0;
    const onPointerDown = (e: PointerEvent) => {
      startX = e.clientX;
      startY = e.clientY;
    };
    const onPointerUp = (e: PointerEvent) => {
      if (Math.hypot(e.clientX - startX, e.clientY - startY) > 5) return;
      if (!measureModeRef.current) return;

      const rect = renderer.domElement.getBoundingClientRect();
      const mouse = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1
      );
      const raycaster = new THREE.Raycaster();
      raycaster.params.Points = { threshold: 0.25 };
      raycaster.setFromCamera(mouse, camera);

      let clickedPoint: THREE.Vector3 | null = null;
      if (pointsRef.current) {
        const hits = raycaster.intersectObject(pointsRef.current);
        if (hits.length > 0) clickedPoint = hits[0].point.clone();
      }
      if (!clickedPoint && bimGroupRef.current) {
        const bimHits = raycaster.intersectObjects(bimGroupRef.current.children, true);
        if (bimHits.length > 0) clickedPoint = bimHits[0].point.clone();
      }
      if (!clickedPoint) {
        const plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
        const target = new THREE.Vector3();
        if (raycaster.ray.intersectPlane(plane, target)) clickedPoint = target;
      }
      if (clickedPoint) {
        const curPts = measurePointsRef.current;
        if (curPts.length === 0 || curPts.length >= 2) {
          const nextPts = [clickedPoint];
          setMeasurePoints(nextPts);
          setMeasureResult(null);
          updateMeasureVisuals(nextPts);
        } else {
          const p1 = curPts[0];
          const p2 = clickedPoint;
          const nextPts = [p1, p2];
          setMeasurePoints(nextPts);
          updateMeasureVisuals(nextPts);

          const dist3d = p1.distanceTo(p2);
          const dx = Math.abs(p2.x - p1.x);
          const dy = Math.abs(p2.y - p1.y);
          const dz = p2.z - p1.z;
          const dxy = Math.hypot(dx, dy);
          const angleDeg = Math.abs(Math.atan2(Math.abs(dz), dxy) * (180 / Math.PI));
          setMeasureResult({ dist3d, dx, dy, dz, dxy, angleDeg });
        }
      }
    };
    renderer.domElement.addEventListener("pointerdown", onPointerDown);
    renderer.domElement.addEventListener("pointerup", onPointerUp);

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
    const fpsSampler = new RenderFpsSampler();
    const animate = (time = performance.now()) => {
      frame = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
      const measuredFps = fpsSampler.sample(time);
      if (measuredFps !== null) setFps(measuredFps);
    };
    animate();
    return () => {
      renderer.domElement.removeEventListener("pointerdown", onPointerDown);
      renderer.domElement.removeEventListener("pointerup", onPointerUp);
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
    if (cloud?.bbox_min && cloud?.bbox_max && cloud.origin) {
      setLimitBox({
        minX: cloud.bbox_min[0] - cloud.origin[0] - 1.0,
        maxX: cloud.bbox_max[0] - cloud.origin[0] + 1.0,
        minY: cloud.bbox_min[1] - cloud.origin[1] - 1.0,
        maxY: cloud.bbox_max[1] - cloud.origin[1] + 1.0,
        minZ: cloud.bbox_min[2] - cloud.origin[2] - 0.5,
        maxZ: cloud.bbox_max[2] - cloud.origin[2] + 0.5,
        invert: false,
      });
    }
  }, [cloud?.id]);

  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;

    if (showLimitBox) {
      const box = new THREE.Box3(
        new THREE.Vector3(limitBox.minX, limitBox.minY, limitBox.minZ),
        new THREE.Vector3(limitBox.maxX, limitBox.maxY, limitBox.maxZ)
      );
      if (!limitBoxHelperRef.current) {
        const helper = new THREE.Box3Helper(box, new THREE.Color(0xff812e));
        helper.renderOrder = 9999;
        scene.add(helper);
        limitBoxHelperRef.current = helper;
      } else {
        limitBoxHelperRef.current.box = box;
        limitBoxHelperRef.current.visible = true;
      }

      const sign = limitBox.invert ? -1 : 1;
      const planes = [
        new THREE.Plane(new THREE.Vector3(sign * 1, 0, 0), -sign * limitBox.minX),
        new THREE.Plane(new THREE.Vector3(-sign * 1, 0, 0), sign * limitBox.maxX),
        new THREE.Plane(new THREE.Vector3(0, sign * 1, 0), -sign * limitBox.minY),
        new THREE.Plane(new THREE.Vector3(0, -sign * 1, 0), sign * limitBox.maxY),
        new THREE.Plane(new THREE.Vector3(0, 0, sign * 1), -sign * limitBox.minZ),
        new THREE.Plane(new THREE.Vector3(0, 0, -sign * 1), sign * limitBox.maxZ),
      ];
      activeClippingPlanesRef.current = planes;
      if (materialRef.current) {
        materialRef.current.clippingPlanes = planes;
      }
      if (bimGroupRef.current) {
        bimGroupRef.current.traverse((child) => {
          if ((child as any).material) {
            (child as any).material.clippingPlanes = planes;
          }
        });
      }
    } else {
      if (limitBoxHelperRef.current) limitBoxHelperRef.current.visible = false;
      activeClippingPlanesRef.current = [];
      if (materialRef.current) {
        materialRef.current.clippingPlanes = [];
      }
      if (bimGroupRef.current) {
        bimGroupRef.current.traverse((child) => {
          if ((child as any).material) {
            (child as any).material.clippingPlanes = [];
          }
        });
      }
    }
  }, [showLimitBox, limitBox]);

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
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    let manifest: LodManifest | null = null;
    let activeLevel: number | null = null;
    let pendingLevel: number | null = null;
    let lodRequest: AbortController | null = null;
    let lodTimer = 0;

    const installBuffer = (buffer: ArrayBuffer): number => {
      if (buffer.byteLength === 0 || buffer.byteLength % 15 !== 0) {
        throw new Error("LOD point buffer must use 15-byte XYZ/RGB records");
      }
      const count = buffer.byteLength / 15;
      const view = new DataView(buffer);
      const positions = new Float32Array(count * 3);
      const z = new Float32Array(count);
      const colors = new Uint8Array(count * 3);
      let maxRadius = 0;
      for (let i = 0; i < count; i += 1) {
        const offset = i * 15;
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
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      const shownColors = colorMode === "rgb" && cloud.has_color ? colors : heightColors(z);
      geometry.setAttribute("color", new THREE.BufferAttribute(shownColors, 3, true));
      geometry.computeBoundingSphere();
      const material = new THREE.PointsMaterial({
        size: Math.max(0.004, maxRadius / 600) * pointSize,
        vertexColors: true,
        sizeAttenuation: true,
        transparent: false,
      });
      if (activeClippingPlanesRef.current.length > 0) {
        material.clippingPlanes = activeClippingPlanesRef.current;
      }
      const points = new THREE.Points(geometry, material);
      points.frustumCulled = false;
      if (pointsRef.current) {
        scene.remove(pointsRef.current);
        pointsRef.current.geometry.dispose();
        materialRef.current?.dispose();
      }
      scene.add(points);
      pointsRef.current = points;
      materialRef.current = material;
      setLoaded(count);
      return maxRadius;
    };

    const fetchLevel = async (level: number): Promise<boolean> => {
      if (!manifest || controller.signal.aborted) return false;
      lodRequest?.abort();
      const request = new AbortController();
      lodRequest = request;
      try {
        const response = await fetch(api.lodBinaryUrl(cloud.id, level), { signal: request.signal });
        if (!response.ok) throw new Error(`LOD ${level} HTTP ${response.status}`);
        const buffer = await response.arrayBuffer();
        if (controller.signal.aborted || request.signal.aborted || lodRequest !== request) return false;
        installBuffer(buffer);
        activeLevel = level;
        pendingLevel = level;
        setError(null);
        return true;
      } catch (reason: any) {
        if (reason?.name !== "AbortError" && !controller.signal.aborted) {
          setError(String(reason?.message || reason));
        }
        return false;
      } finally {
        if (lodRequest === request) lodRequest = null;
        if (pendingLevel === level && activeLevel !== level && !request.signal.aborted) {
          pendingLevel = null;
        }
      }
    };

    const scheduleLevelForCamera = () => {
      if (!manifest || !camera || !controls) return;
      const target = selectLodLevel(manifest.levels, camera.position.distanceTo(controls.target));
      if (target == null) return;
      if (target === activeLevel) {
        if (lodTimer) window.clearTimeout(lodTimer);
        lodTimer = 0;
        pendingLevel = activeLevel;
        lodRequest?.abort();
        return;
      }
      if (target === pendingLevel) return;
      if (lodTimer) window.clearTimeout(lodTimer);
      pendingLevel = target;
      lodTimer = window.setTimeout(() => {
        lodTimer = 0;
        void fetchLevel(target);
      }, 140);
    };

    setLoading(true);
    setError(null);
    (async () => {
      try {
        try {
          manifest = await api.getLodManifest(cloud.id);
          if (manifest.levels.length > 0 && camera && controls) {
            const size = manifest.bounds.size;
            const sphere = new THREE.Sphere(
              new THREE.Vector3(...manifest.bounds.center),
              Math.max(1, Math.hypot(...size) / 2),
            );
            const aspect = Math.max(0.1, camera.aspect || 1);
            const initialDistance = groupCameraDistance(sphere.radius, camera.fov, aspect);
            const initialLevel = selectLodLevel(manifest.levels, initialDistance);
            if (initialLevel != null && await fetchLevel(initialLevel)) {
              fitSphere(groupSphereRef.current ?? sphere);
              controls.addEventListener("change", scheduleLevelForCamera);
              scheduleLevelForCamera();
              return;
            }
          }
        } catch {
          manifest = null;
        }

        manifest = null;
        const response = await fetch(api.previewUrl(cloud.id), { signal: controller.signal });
        if (!response.ok) throw new Error(`preview HTTP ${response.status}`);
        const maxRadius = installBuffer(await response.arrayBuffer());
        setError(null);
        fitSphere(groupSphereRef.current ?? new THREE.Sphere(new THREE.Vector3(), Math.max(1, maxRadius)));
      } catch (err: any) {
        if (err?.name !== "AbortError") setError(String(err?.message || err));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => {
      controller.abort();
      lodRequest?.abort();
      if (lodTimer) window.clearTimeout(lodTimer);
      controls?.removeEventListener("change", scheduleLevelForCamera);
    };
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
    let colors: Uint8Array;
    if (colorMode === "rgb" && cloud?.has_color && raw.colors) {
      colors = raw.colors;
    } else {
      colors = heightColors(raw.z);
    }
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

  // Structural SPDS Grid Effect (3 Spans, 4 Rows: А, Б, В, Г, 24 Axes: 1..24, step 6000 mm)
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;

    if (gridGroupRef.current) {
      scene.remove(gridGroupRef.current);
      gridGroupRef.current.traverse((child) => {
        if (child instanceof THREE.LineSegments || child instanceof THREE.Sprite) {
          child.geometry?.dispose();
          if (Array.isArray(child.material)) child.material.forEach((m) => m.dispose());
          else child.material?.dispose();
        }
      });
      gridGroupRef.current = null;
    }

    if (!showGrid) return;

    const origin = cloud?.origin || [0, 0, 0];
    const gridData = computeStructuralGridGeometry(origin);
    const group = new THREE.Group();
    group.name = "structural-spds-grid";

    // 1. Transverse lines (Axes 1..24, step 6000 mm)
    const tGeom = new THREE.BufferGeometry();
    tGeom.setAttribute("position", new THREE.BufferAttribute(gridData.transverseLinePositions, 3));
    const tMat = new THREE.LineBasicMaterial({
      color: 0x64748b, // SPDS axis slate blue
      transparent: true,
      opacity: 0.65,
      depthTest: false,
    });
    const tLines = new THREE.LineSegments(tGeom, tMat);
    tLines.renderOrder = 4;
    group.add(tLines);

    // 2. Longitudinal lines (Rows А, Б, В, Г for the 3 spans)
    const lGeom = new THREE.BufferGeometry();
    lGeom.setAttribute("position", new THREE.BufferAttribute(gridData.longitudinalLinePositions, 3));
    const lMat = new THREE.LineBasicMaterial({
      color: 0x0284c7, // Structural blue
      transparent: true,
      opacity: 0.85,
      depthTest: false,
    });
    const lLines = new THREE.LineSegments(lGeom, lMat);
    lLines.renderOrder = 4;
    group.add(lLines);

    // 3. Axis bubbles with crisp high-res canvas sprites
    const createBubbleTexture = (text: string, isRow: boolean) => {
      const canvas = document.createElement("canvas");
      canvas.width = 128;
      canvas.height = 128;
      const ctx = canvas.getContext("2d");
      if (!ctx) return null;

      ctx.beginPath();
      ctx.arc(64, 64, 56, 0, Math.PI * 2);
      ctx.fillStyle = isRow ? "#0284c7" : "#334155";
      ctx.fill();
      ctx.lineWidth = 6;
      ctx.strokeStyle = "#ffffff";
      ctx.stroke();

      ctx.fillStyle = "#ffffff";
      ctx.font = "bold 52px system-ui, -apple-system, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(text, 64, 64);

      return new THREE.CanvasTexture(canvas);
    };

    gridData.bubbleNodes.forEach((node) => {
      const tex = createBubbleTexture(node.label, node.type === "row");
      if (!tex) return;
      const spriteMat = new THREE.SpriteMaterial({
        map: tex,
        transparent: true,
        depthTest: false,
      });
      const sprite = new THREE.Sprite(spriteMat);
      sprite.position.set(node.position[0], node.position[1], node.position[2]);
      sprite.scale.set(2.4, 2.4, 1.0);
      sprite.renderOrder = 12;
      group.add(sprite);
    });

    scene.add(group);
    gridGroupRef.current = group;
  }, [showGrid, cloud?.origin]);

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
      { key: "stair", color: 0xea580c, visible: showStairs, renderOrder: 5 },
      { key: "opening", color: 0xef4444, visible: showOpenings, renderOrder: 4 },
      { key: "pipe", color: 0x06b6d4, visible: showPipes, renderOrder: 3 },
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
  }, [elements, cloud?.origin, showColumns, showBeams, showBraces, showTrusses, showWalls, showStairs, showOpenings, showPipes]);

  const selectedDims = selectedElement?.dimensions || {};
  const nominalGrid = selectedDims.nominal_grid_hypothesis?.grid_hypothesis;
  const oldGridOnly = selectedElement?.source === "structural_grid"
    || (selectedDims.structural_status === "confirmed_grid_column"
      && !["confirmed", "corrected"].includes(selectedElement?.review_status || ""));

  return (
    <div className="viewer">
      <div ref={hostRef} className="viewer-canvas" />
      {!hideInternalHud && (
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
          {loaded > 0 && fps !== null && (
            <span
              className={`viewer-fps ${fps >= 55 ? "viewer-fps--good" : fps >= 30 ? "viewer-fps--warning" : "viewer-fps--low"}`}
              role="status"
              aria-live="off"
              title="Кадры WebGL-цикла за последнюю секунду; приёмку производительности выполняйте при активном окне и навигации"
            >
              {fps} FPS
            </span>
          )}
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
          <button
            type="button"
            className="hud-chip"
            style={{
              cursor: "pointer",
              background: showLimitBox ? "#FF812E" : "#1C2430",
              color: showLimitBox ? "#0A0E13" : "#FFFFFF",
              border: "1px solid #FF812E",
              borderRadius: "4px",
              padding: "2px 10px",
              fontWeight: 700,
            }}
            onClick={() => setShowLimitBox(!showLimitBox)}
            title="Интерактивный Limit Box (секущий куб ReCap): обрезка по осям X, Y, Z в реальном времени"
          >
            📦 Limit Box
          </button>
          <button
            type="button"
            className="hud-chip"
            style={{
              cursor: "pointer",
              background: measureMode ? "#38BDF8" : "#1C2430",
              color: measureMode ? "#0A0E13" : "#FFFFFF",
              border: "1px solid #38BDF8",
              borderRadius: "4px",
              padding: "2px 10px",
              fontWeight: 700,
            }}
            onClick={() => {
              const next = !measureMode;
              setMeasureMode(next);
              if (!next) handleClearMeasurement();
            }}
            title="Лазерные 3D замеры ReCap: кликните две точки для замера прямого расстояния, ΔXY и высотного перепада ΔZ"
          >
            📐 Линейка 3D
          </button>
          <button
            type="button"
            className="hud-chip"
            style={{
              cursor: "pointer",
              background: showGrid ? "#475569" : "#f5f2ed",
              color: showGrid ? "#fff" : "#888",
              border: "1px solid #475569",
              borderRadius: "4px",
              padding: "2px 8px",
              fontWeight: showGrid ? 700 : 500,
            }}
            onClick={() => setShowGrid(!showGrid)}
            title="Схематическая сетка-шаблон: шаг 6 м. Начало координат, поворот и поперечные ряды не подтверждены контрольной съёмкой."
          >
            {showGrid ? "📐 Скрыть сетку-шаблон" : "📐 Сетка-шаблон (6 м)"}
          </button>
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
          {(counts.stair || 0) > 0 && (
            <button
              type="button"
              className="hud-chip"
              style={{
                cursor: "pointer",
                background: showStairs ? "#ea580c" : "#f5f2ed",
                color: showStairs ? "#fff" : "#888",
                border: "1px solid #ea580c",
                borderRadius: "4px",
                padding: "2px 8px",
              }}
              onClick={() => { setActivePreset("custom"); setShowStairs(!showStairs); }}
              title="Показать / скрыть лестничные марши"
            >
              🪜 Лестницы ({counts.stair})
            </button>
          )}
          {(counts.opening || 0) > 0 && (
            <button
              type="button"
              className="hud-chip"
              style={{
                cursor: "pointer",
                background: showOpenings ? "#dc2626" : "#f5f2ed",
                color: showOpenings ? "#fff" : "#888",
                border: "1px solid #dc2626",
                borderRadius: "4px",
                padding: "2px 8px",
              }}
              onClick={() => { setActivePreset("custom"); setShowOpenings(!showOpenings); }}
              title="Показать / скрыть проёмы (двери, окна)"
            >
              🚪 Проёмы ({counts.opening})
            </button>
          )}
          {(counts.pipe || 0) > 0 && (
            <button
              type="button"
              className="hud-chip"
              style={{
                cursor: "pointer",
                background: showPipes ? "#0891b2" : "#f5f2ed",
                color: showPipes ? "#fff" : "#888",
                border: "1px solid #0891b2",
                borderRadius: "4px",
                padding: "2px 8px",
              }}
              onClick={() => { setActivePreset("custom"); setShowPipes(!showPipes); }}
              title="Показать / скрыть трубопроводы и инженерные сети (MEP)"
            >
              🔧 Трубы ({counts.pipe})
            </button>
          )}
          {cloud?.decimated && <span className="warn">прорежено</span>}
          {groupPositions.length > 0 && <span>контуры группы: {groupPositions.length / 72}</span>}
        </div>
      </div>
      )}
      {selectedElement && (
        <div
          className="viewer-selected-card"
          style={{
            position: "absolute",
            bottom: "16px",
            left: "16px",
            background: "rgba(15, 23, 42, 0.90)",
            backdropFilter: "blur(10px)",
            color: "#fff",
            padding: "12px 16px",
            borderRadius: "8px",
            border: "1px solid rgba(56, 189, 248, 0.6)",
            boxShadow: "0 8px 24px rgba(0, 0, 0, 0.35)",
            fontSize: "13px",
            maxWidth: "460px",
            pointerEvents: "auto",
            zIndex: 10,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
            <span style={{ fontWeight: 700, fontSize: "15px", color: "#38bdf8" }}>
              {oldGridOnly ? classLabel(selectedElement.class_name) : selectedElement.dimensions?.mark || classLabel(selectedElement.class_name)}
            </span>
            <span style={{ fontSize: "11px", background: "#0284c7", padding: "2px 8px", borderRadius: "4px", fontWeight: 600 }}>
              {oldGridOnly ? "требует проверки" : selectedElement.dimensions?.type || classLabel(selectedElement.class_name)}
            </span>
          </div>
          <div style={{ color: "#cbd5e1", lineHeight: "1.45" }}>
            {nominalGrid && (
              <div style={{ color: "#fbbf24" }}>
                {nominalGrid.status === "grid_control_not_provided"
                  ? `Контрольная сетка не задана. Известен только продольный шаг ${nominalGrid.nominal_step_m ?? "—"} м; номера осей не рассчитаны.`
                  : <>Гипотеза сетки: ряд <b>{nominalGrid.row ?? "—"}</b> · ось <b>{nominalGrid.axis ?? "—"}</b> · ΔU={nominalGrid.delta_u_mm ?? "—"} мм · ΔV={nominalGrid.delta_v_mm ?? "—"} мм. Требуется проверка.</>}
              </div>
            )}
            {!oldGridOnly && selectedElement.dimensions?.height_m && selectedElement.dimensions?.length_m && selectedElement.dimensions?.thickness_m && (
              <div>Высота: <b>{selectedElement.dimensions.height_m} м</b> · Сечение: <b>{Math.round(selectedElement.dimensions.length_m * 1000)}×{Math.round(selectedElement.dimensions.thickness_m * 1000)} мм</b></div>
            )}
            {nominalGrid && nominalGrid.status !== "grid_control_not_provided" && (
              <div style={{ color: "#7dd3fc" }}>
                Смещение от номинальной позиции — диагностический остаток, не инженерный допуск.
              </div>
            )}
            {(oldGridOnly || selectedElement.dimensions?.tolerance_badge) && (
              <div style={{
                marginTop: "6px",
                padding: "3px 8px",
                borderRadius: "4px",
                background: "rgba(245, 158, 11, 0.18)",
                border: "1px solid #f59e0b",
                color: "#fff",
                fontSize: "11px",
                fontWeight: 600,
              }}>
                Старый статус допуска не подтверждён контрольными измерениями.
              </div>
            )}
            {selectedElement.dimensions?.description && (
              <div style={{ fontSize: "11px", color: "#94a3b8", marginTop: "4px" }}>
                {selectedElement.dimensions.description}
              </div>
            )}
          </div>
        </div>
      )}
      {["intensity", "normals", "error"].includes(colorMode) && (
        <div className="viewer-error" role="status">Данные выбранного режима не переданы. Показана высота Z.</div>
      )}
      {error && <div className="viewer-error">{error}</div>}
      {!cloud && <div className="viewer-empty">Импортируйте облако точек или загрузите демо-комнату</div>}
      {/* ReCap Limit Box Dock */}
      <LimitBoxDock
        visible={isLimitBoxOpen}
        onClose={() => {
          setShowLimitBox(false);
          onToggleLimitBox?.(false);
        }}
        box={limitBox}
        onChange={(b) => setLimitBox(b)}
        onPreset={handleLimitBoxPreset}
      />

      {/* ReCap 3D Laser Measurement Dock */}
      <Measure3DDock
        active={isMeasureActive}
        onToggle={() => {
          setMeasureMode(false);
          onToggleMeasureMode?.(false);
          handleClearMeasurement();
        }}
        result={measureResult}
        pointCount={measurePoints.length}
        onClear={handleClearMeasurement}
      />
    </div>
  );
}
