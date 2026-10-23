export interface LodDistanceLevel {
  level: number;
  distance_min: number;
  distance_max: number;
}

/** Select the closest-detail level whose distance interval contains the camera. */
export function selectLodLevel(
  levels: readonly LodDistanceLevel[],
  distance: number,
): number | null {
  if (!Number.isFinite(distance) || distance < 0 || levels.length === 0) return null;
  const valid = levels
    .filter((item) => Number.isInteger(item.level) && item.level >= 0 && Number.isFinite(item.distance_min) &&
      Number.isFinite(item.distance_max) && item.distance_min >= 0 && item.distance_max >= item.distance_min)
    .slice()
    .sort((a, b) => b.distance_min - a.distance_min || a.level - b.level);
  if (valid.length === 0) return null;
  const matching = valid.find((item) => distance >= item.distance_min && distance <= item.distance_max);
  if (matching) return matching.level;

  // Malformed or non-contiguous manifests still get the nearest declared level.
  const nearest = valid.reduce((best, item) => {
    const gap = distance < item.distance_min
      ? item.distance_min - distance
      : distance - item.distance_max;
    const bestGap = distance < best.distance_min
      ? best.distance_min - distance
      : distance - best.distance_max;
    return gap < bestGap ? item : best;
  });
  return nearest.level;
}
