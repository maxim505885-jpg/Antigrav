type Bbox = { min?: number[]; max?: number[] } | null | undefined;

export function bboxExtentsMm(bbox: Bbox): [number, number, number] | null {
  if (!bbox || !Array.isArray(bbox.min) || !Array.isArray(bbox.max)
      || bbox.min.length < 3 || bbox.max.length < 3) return null;
  const extents = [0, 1, 2].map((axis) => {
    const low = bbox.min![axis];
    const high = bbox.max![axis];
    return typeof low === "number" && typeof high === "number" && Number.isFinite(low) && Number.isFinite(high) && high >= low
      ? Math.round((high - low) * 1000)
      : null;
  });
  return extents.every((value): value is number => value !== null)
    ? extents as [number, number, number]
    : null;
}
