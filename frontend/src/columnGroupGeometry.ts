interface GroupElement {
  id: string;
  class_name: string;
  measured: boolean;
  inferred: boolean;
  geometry: Record<string, any>;
}

export function groupCameraDistance(radius: number, verticalFovDegrees: number, aspect: number): number {
  if (![radius, verticalFovDegrees, aspect].every(Number.isFinite) || radius <= 0 || aspect <= 0 ||
    verticalFovDegrees <= 0 || verticalFovDegrees >= 180) throw new Error("Invalid camera bounds");
  const halfVertical = verticalFovDegrees * Math.PI / 360;
  const halfHorizontal = Math.atan(Math.tan(halfVertical) * aspect);
  return radius / Math.sin(Math.min(halfVertical, halfHorizontal)) * 1.1;
}

/** Measured oriented-box edges in the same local frame as the cloud preview. */
export function columnGroupLinePositions(
  elements: readonly GroupElement[], ids: readonly string[], origin: readonly number[] = [0, 0, 0],
): { positions: Float32Array; rendered_ids: string[]; unavailable_ids: string[] } {
  const byId = new Map(elements.map((element) => [element.id, element]));
  const positions: number[] = [], rendered_ids: string[] = [], unavailable_ids: string[] = [];
  for (const id of new Set(ids)) {
    const element = byId.get(id);
    const geometry = element?.geometry;
    const sizes = geometry?.sizes;
    const center = geometry?.center;
    const angle = geometry?.rotation_z;
    if (!element || element.class_name !== "column" || !element.measured || element.inferred ||
      geometry?.kind !== "oriented_box" || !Array.isArray(center) || center.length !== 3 ||
      !center.every((value) => typeof value === "number" && Number.isFinite(value)) ||
      typeof angle !== "number" || !Number.isFinite(angle) ||
      ![sizes?.length, sizes?.thickness, sizes?.height].every((value) =>
        typeof value === "number" && Number.isFinite(value) && value > 0)) {
      unavailable_ids.push(id);
      continue;
    }
    const c = Math.cos(angle), s = Math.sin(angle);
    const corners = Array.from({ length: 8 }, (_, index) => {
      const x = (index & 1 ? 1 : -1) * sizes.length / 2;
      const y = (index & 2 ? 1 : -1) * sizes.thickness / 2;
      return [center[0] - (origin[0] ?? 0) + x * c - y * s,
        center[1] - (origin[1] ?? 0) + x * s + y * c,
        center[2] - (origin[2] ?? 0) + (index & 4 ? 1 : -1) * sizes.height / 2];
    });
    for (let index = 0; index < 8; index++) {
      for (const axis of [1, 2, 4]) {
        if (!(index & axis)) positions.push(...corners[index], ...corners[index | axis]);
      }
    }
    rendered_ids.push(id);
  }
  return { positions: new Float32Array(positions), rendered_ids, unavailable_ids };
}
