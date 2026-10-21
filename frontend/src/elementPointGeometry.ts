export function toLocalElementPositions(
  points: number[][],
  origin: number[] | null | undefined,
): Float32Array {
  const offset = origin ?? [0, 0, 0];
  const positions = new Float32Array(points.length * 3);
  points.forEach((point, index) => {
    positions[index * 3] = point[0] - (offset[0] ?? 0);
    positions[index * 3 + 1] = point[1] - (offset[1] ?? 0);
    positions[index * 3 + 2] = point[2] - (offset[2] ?? 0);
  });
  return positions;
}

export function sliceElementPositions(
  points: number[][],
  bbox: { min: number[]; max: number[] },
  origin: number[] | null | undefined,
): [Float32Array, Float32Array, Float32Array] {
  const offset = origin ?? [0, 0, 0];
  const min = bbox.min.map((value, axis) => value - (offset[axis] ?? 0));
  const max = bbox.max.map((value, axis) => value - (offset[axis] ?? 0));
  const centers = min.map((value, axis) => (value + max[axis]) / 2);
  const halfWidths = min.map((value, axis) => Math.max(0.01, (max[axis] - value) * 0.02));
  const slices: [number[], number[], number[]] = [[], [], []];

  for (const point of points) {
    const local = point.map((value, axis) => value - (offset[axis] ?? 0));
    if (local.some((value, axis) => value < min[axis] || value > max[axis])) continue;
    for (let axis = 0; axis < 3; axis += 1) {
      if (Math.abs(local[axis] - centers[axis]) <= halfWidths[axis]) slices[axis].push(...local);
    }
  }
  return slices.map((values) => Float32Array.from(values)) as [Float32Array, Float32Array, Float32Array];
}
