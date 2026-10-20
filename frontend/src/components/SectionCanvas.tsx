import { useEffect, useRef } from "react";
import type { SectionResult } from "../types";

interface Props {
  result: SectionResult | null;
}

interface View {
  scale: number;
  tx: number;
  ty: number;
  fitScale: number;
  fitTx: number;
  fitTy: number;
  dragging: { x: number; y: number } | null;
}

export default function SectionCanvas({ result }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewRef = useRef<View>({ scale: 1, tx: 0, ty: 0, fitScale: 1, fitTx: 0, fitTy: 0, dragging: null });
  const drawRef = useRef<() => void>(() => {});
  const sizeRef = useRef({ width: 0, height: 0 });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const getBounds = () => {
      let minU = Infinity;
      let maxU = -Infinity;
      let minV = Infinity;
      let maxV = -Infinity;
      const add = (u: number, v: number) => {
        if (u < minU) minU = u;
        if (u > maxU) maxU = u;
        if (v < minV) minV = v;
        if (v > maxV) maxV = v;
      };
      result?.polygons.forEach((poly) => poly.points.forEach(([u, v]) => add(u, v)));
      if (!Number.isFinite(minU)) {
        result?.preview_points.forEach(([u, v]) => add(u, v));
      }
      if (!Number.isFinite(minU)) return { minU: -1, maxU: 1, minV: -1, maxV: 1 };
      return { minU, maxU, minV, maxV };
    };

    const fit = () => {
      const { width, height } = sizeRef.current;
      if (!width || !height) return;
      const b = getBounds();
      const bw = Math.max(1e-3, b.maxU - b.minU);
      const bh = Math.max(1e-3, b.maxV - b.minV);
      const scale = Math.min((width - 64) / bw, (height - 64) / bh);
      const cx = (b.minU + b.maxU) / 2;
      const cy = (b.minV + b.maxV) / 2;
      const view = viewRef.current;
      view.scale = scale;
      view.tx = width / 2 - cx * scale;
      view.ty = height / 2 + cy * scale;
      view.fitScale = view.scale;
      view.fitTx = view.tx;
      view.fitTy = view.ty;
    };

    const draw = () => {
      const { width, height } = sizeRef.current;
      const dpr = canvas.width / Math.max(1, width);
      const view = viewRef.current;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = "#0d1117";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      if (!result || width === 0) {
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.fillStyle = "#8b949e";
        ctx.font = "13px system-ui";
        ctx.fillText("Постройте сечение, чтобы увидеть измеренную геометрию", 16, 28);
        return;
      }
      ctx.setTransform(dpr * view.scale, 0, 0, -dpr * view.scale, dpr * view.tx, dpr * view.ty);

      if (result.preview_points.length) {
        ctx.fillStyle = "rgba(150, 170, 195, 0.35)";
        const step = Math.max(1, Math.ceil(result.preview_points.length / 25000));
        for (let i = 0; i < result.preview_points.length; i += step) {
          const [u, v] = result.preview_points[i];
          const s = 1.4 / view.scale;
          ctx.fillRect(u - s / 2, v - s / 2, s, s);
        }
      }

      result.polygons.forEach((poly) => {
        if (!poly.points.length) return;
        ctx.beginPath();
        poly.points.forEach(([u, v], index) => {
          if (index === 0) ctx.moveTo(u, v);
          else ctx.lineTo(u, v);
        });
        ctx.closePath();
        if (!poly.is_hole) {
          ctx.fillStyle = "rgba(77, 163, 255, 0.12)";
          ctx.fill();
          ctx.strokeStyle = "#7cc4ff";
          ctx.lineWidth = 1.6 / view.scale;
        } else {
          ctx.strokeStyle = "rgba(255, 156, 110, 0.9)";
          ctx.lineWidth = 1.2 / view.scale;
          ctx.setLineDash([6 / view.scale, 4 / view.scale]);
        }
        ctx.stroke();
        ctx.setLineDash([]);
      });

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = "#c9d1d9";
      ctx.font = "12px system-ui";
      const holes = result.polygons.filter((p) => p.is_hole).length;
      ctx.fillText(
        `${result.frame.u_label}/${result.frame.v_label} · контуров: ${result.polygons.length} (отверстий: ${holes}) · ` +
          `точек в слое: ${result.point_count.toLocaleString()} · площадь ${result.total_area_m2.toFixed(2)} м²`,
        16,
        height - 16,
      );
      ctx.fillStyle = "#3fb950";
      ctx.fillText(`смещение ${result.frame.u_label}:${result.frame.world_offset[0].toFixed(2)} м  ` +
        `${result.frame.v_label}:${result.frame.world_offset[1].toFixed(2)} м`, 16, height - 34);
    };
    drawRef.current = draw;

    const resize = () => {
      const parent = canvas.parentElement;
      if (!parent) return;
      const dpr = Math.min(window.devicePixelRatio, 2);
      const width = parent.clientWidth;
      const height = parent.clientHeight;
      if (!width || !height) return;
      sizeRef.current = { width, height };
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      // All drawing uses CSS pixel coordinates; the DPR is applied in draw().
      sizeRef.current = { width, height };
      const view = viewRef.current;
      if (view.fitScale === 1 && view.tx === 0 && view.ty === 0) fit();
      draw();
    };

    const observer = new ResizeObserver(resize);
    if (canvas.parentElement) observer.observe(canvas.parentElement);
    resize();
    fit();
    draw();

    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const mx = event.clientX - rect.left;
      const my = event.clientY - rect.top;
      const view = viewRef.current;
      const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
      const wx = (mx - view.tx) / view.scale;
      const wy = (view.ty - my) / view.scale;
      view.scale = Math.max(view.fitScale * 0.05, Math.min(view.fitScale * 200, view.scale * factor));
      view.tx = mx - wx * view.scale;
      view.ty = my + wy * view.scale;
      draw();
    };
    const onPointerDown = (event: PointerEvent) => {
      viewRef.current.dragging = { x: event.clientX, y: event.clientY };
      canvas.setPointerCapture(event.pointerId);
    };
    const onPointerMove = (event: PointerEvent) => {
      const dragging = viewRef.current.dragging;
      if (!dragging) return;
      const dx = event.clientX - dragging.x;
      const dy = event.clientY - dragging.y;
      dragging.x = event.clientX;
      dragging.y = event.clientY;
      viewRef.current.tx += dx;
      viewRef.current.ty += dy;
      draw();
    };
    const onPointerUp = () => {
      viewRef.current.dragging = null;
    };
    const onDoubleClick = () => {
      fit();
      draw();
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("dblclick", onDoubleClick);
    return () => {
      observer.disconnect();
      canvas.removeEventListener("wheel", onWheel);
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerup", onPointerUp);
      canvas.removeEventListener("dblclick", onDoubleClick);
    };
  }, [result]);

  return (
    <div className="section-canvas-wrap">
      <canvas ref={canvasRef} className="section-canvas" />
    </div>
  );
}
