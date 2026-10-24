export interface BoxCandidate {
  id: string;
  class_name: string;
  source?: string;
  metadata?: Record<string, unknown>;
  geometry?: Record<string, any>;
  bbox?: { min: number[]; max: number[] };
}

export function elementUsesCloudLocalCoordinates(element: Pick<BoxCandidate, "source" | "metadata">): boolean {
  const frame = element.metadata?.bbox_coordinate_frame;
  if (frame === "cloud_local") return true;
  if (frame === "source_cloud_world") return false;
  return element.source === "geometric" || element.source === "structural_grid";
}

/**
 * Computes 12-edge line segments for a set of structural elements in the cloud's local frame.
 * Uses oriented_box geometry when available, falling back to axis-aligned bbox.
 */
export function elementBoxLinePositions(
  elements: readonly BoxCandidate[],
  className: string,
  origin: readonly number[] = [0, 0, 0],
): Float32Array {
  const positions: number[] = [];
  const ox = origin[0] ?? 0;
  const oy = origin[1] ?? 0;
  const oz = origin[2] ?? 0;

  for (const el of elements) {
    if (className !== "all" && el.class_name !== className) continue;
    const elementIsLocal = elementUsesCloudLocalCoordinates(el);
    const oxForElement = elementIsLocal ? 0 : ox;
    const oyForElement = elementIsLocal ? 0 : oy;
    const ozForElement = elementIsLocal ? 0 : oz;

    let cx = 0, cy = 0, cz = 0;
    let lx = 0, ly = 0, lz = 0;
    let angle = 0;

    const geom = el.geometry;
    if (
      geom?.kind === "oriented_box" &&
      Array.isArray(geom.center) &&
      geom.sizes &&
      typeof geom.rotation_z === "number"
    ) {
      cx = geom.center[0] - oxForElement;
      cy = geom.center[1] - oyForElement;
      cz = geom.center[2] - ozForElement;
      lx = geom.sizes.length || 0.5;
      ly = geom.sizes.thickness || 0.5;
      lz = geom.sizes.height || 1.0;
      angle = geom.rotation_z;
    } else if (el.bbox && Array.isArray(el.bbox.min) && Array.isArray(el.bbox.max)) {
      const bmin = el.bbox.min;
      const bmax = el.bbox.max;
      cx = (bmin[0] + bmax[0]) / 2 - oxForElement;
      cy = (bmin[1] + bmax[1]) / 2 - oyForElement;
      cz = (bmin[2] + bmax[2]) / 2 - ozForElement;
      lx = Math.max(0.05, bmax[0] - bmin[0]);
      ly = Math.max(0.05, bmax[1] - bmin[1]);
      lz = Math.max(0.05, bmax[2] - bmin[2]);
      angle = 0;
    } else {
      continue;
    }

    if (!Number.isFinite(cx) || !Number.isFinite(cy) || !Number.isFinite(cz) ||
        lx <= 0 || ly <= 0 || lz <= 0) {
      continue;
    }

    const c = Math.cos(angle);
    const s = Math.sin(angle);
    const hx = lx / 2;
    const hy = ly / 2;
    const hz = lz / 2;

    const corners: [number, number, number][] = [
      [cx + (-hx) * c - (-hy) * s, cy + (-hx) * s + (-hy) * c, cz - hz],
      [cx + (hx) * c - (-hy) * s,  cy + (hx) * s + (-hy) * c,  cz - hz],
      [cx + (-hx) * c - (hy) * s,  cy + (-hx) * s + (hy) * c,  cz - hz],
      [cx + (hx) * c - (hy) * s,   cy + (hx) * s + (hy) * c,   cz - hz],
      [cx + (-hx) * c - (-hy) * s, cy + (-hx) * s + (-hy) * c, cz + hz],
      [cx + (hx) * c - (-hy) * s,  cy + (hx) * s + (-hy) * c,  cz + hz],
      [cx + (-hx) * c - (hy) * s,  cy + (-hx) * s + (hy) * c,  cz + hz],
      [cx + (hx) * c - (hy) * s,   cy + (hx) * s + (hy) * c,   cz + hz],
    ];

    for (let i = 0; i < 8; i++) {
      for (const axis of [1, 2, 4]) {
        if (!(i & axis)) {
          const a = corners[i];
          const b = corners[i | axis];
          positions.push(a[0], a[1], a[2], b[0], b[1], b[2]);
        }
      }
    }
  }

  return new Float32Array(positions);
}
