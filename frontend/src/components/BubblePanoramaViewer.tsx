import React, { useEffect, useRef, useState } from "react";
import * as THREE from "three";

interface Props {
  stationName: string;
  stationPosition: [number, number, number];
  onClose?: () => void;
  imageUrl?: string;
}

export const BubblePanoramaViewer: React.FC<Props> = ({
  stationName,
  stationPosition,
  onClose,
  imageUrl,
}) => {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [coords, setCoords] = useState<{ x: number; y: number; z: number }>({
    x: stationPosition[0],
    y: stationPosition[1],
    z: stationPosition[2],
  });

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const width = mount.clientWidth || 800;
    const height = mount.clientHeight || 500;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, width / height, 0.1, 1000);
    camera.position.set(0, 0, 0.1);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    mount.appendChild(renderer.domElement);

    // Create inverted sphere for bubble panoramic view
    const geometry = new THREE.SphereGeometry(50, 60, 40);
    // Invert geometry so faces point inward
    geometry.scale(-1, 1, 1);

    let material: THREE.Material;
    if (imageUrl) {
      const texture = new THREE.TextureLoader().load(imageUrl);
      material = new THREE.MeshBasicMaterial({ map: texture });
    } else {
      // Procedural synthetic grid texture when photo is not present
      const canvas = document.createElement("canvas");
      canvas.width = 1024;
      canvas.height = 512;
      const ctx = canvas.getContext("2d")!;
      ctx.fillStyle = "#1e293b";
      ctx.fillRect(0, 0, 1024, 512);
      ctx.strokeStyle = "#38bdf8";
      ctx.lineWidth = 1;
      for (let i = 0; i < 1024; i += 64) {
        ctx.beginPath();
        ctx.moveTo(i, 0);
        ctx.lineTo(i, 512);
        ctx.stroke();
      }
      for (let j = 0; j < 512; j += 64) {
        ctx.beginPath();
        ctx.moveTo(0, j);
        ctx.lineTo(1024, j);
        ctx.stroke();
      }
      ctx.fillStyle = "#f8fafc";
      ctx.font = "24px sans-serif";
      ctx.fillText(`Стоянка: ${stationName}`, 400, 250);
      const texture = new THREE.CanvasTexture(canvas);
      material = new THREE.MeshBasicMaterial({ map: texture });
    }

    const sphere = new THREE.Mesh(geometry, material);
    scene.add(sphere);

    let isUserInteracting = false;
    let onPointerDownPointerX = 0;
    let onPointerDownPointerY = 0;
    let lon = 0;
    let onPointerDownLon = 0;
    let lat = 0;
    let onPointerDownLat = 0;
    let phi = 0;
    let theta = 0;

    const onPointerDown = (event: PointerEvent) => {
      if (event.isPrimary === false) return;
      isUserInteracting = true;
      onPointerDownPointerX = event.clientX;
      onPointerDownPointerY = event.clientY;
      onPointerDownLon = lon;
      onPointerDownLat = lat;
      document.addEventListener("pointermove", onPointerMove);
      document.addEventListener("pointerup", onPointerUp);
    };

    const onPointerMove = (event: PointerEvent) => {
      if (event.isPrimary === false) return;
      lon = (onPointerDownPointerX - event.clientX) * 0.15 + onPointerDownLon;
      lat = (event.clientY - onPointerDownPointerY) * 0.15 + onPointerDownLat;
    };

    const onPointerUp = (event: PointerEvent) => {
      if (event.isPrimary === false) return;
      isUserInteracting = false;
      document.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("pointerup", onPointerUp);
    };

    mount.addEventListener("pointerdown", onPointerDown);

    let animId: number;
    const animate = () => {
      animId = requestAnimationFrame(animate);
      lat = Math.max(-85, Math.min(85, lat));
      phi = THREE.MathUtils.degToRad(90 - lat);
      theta = THREE.MathUtils.degToRad(lon);

      const target = new THREE.Vector3();
      target.x = 500 * Math.sin(phi) * Math.cos(theta);
      target.y = 500 * Math.cos(phi);
      target.z = 500 * Math.sin(phi) * Math.sin(theta);

      camera.lookAt(target);
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      cancelAnimationFrame(animId);
      mount.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("pointerup", onPointerUp);
      renderer.dispose();
      if (mount.contains(renderer.domElement)) {
        mount.removeChild(renderer.domElement);
      }
    };
  }, [stationName, stationPosition, imageUrl]);

  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        height: "450px",
        borderRadius: "8px",
        overflow: "hidden",
        border: "1px solid rgba(255,255,255,0.15)",
        background: "#000",
      }}
    >
      <div
        style={{
          position: "absolute",
          top: 10,
          left: 10,
          zIndex: 10,
          background: "rgba(15, 23, 42, 0.8)",
          padding: "6px 12px",
          borderRadius: "4px",
          fontSize: "12px",
          color: "#fff",
        }}
      >
        <strong>360° Bubble-View:</strong> {stationName} (X: {coords.x.toFixed(2)}, Y: {coords.y.toFixed(2)}, Z: {coords.z.toFixed(2)} м)
      </div>
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          style={{
            position: "absolute",
            top: 10,
            right: 10,
            zIndex: 10,
            background: "rgba(239, 68, 68, 0.8)",
            color: "#fff",
            border: "none",
            borderRadius: "4px",
            padding: "4px 8px",
            cursor: "pointer",
            fontSize: "12px",
          }}
        >
          Закрыть панораму
        </button>
      )}
      <div ref={mountRef} style={{ width: "100%", height: "100%" }} />
    </div>
  );
};
