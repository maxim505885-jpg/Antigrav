type CloudPointMetadata = {
  point_count: number;
  ingested_count: number;
  decimated?: boolean;
  metadata?: Record<string, unknown>;
};

function countLabel(value: number): string {
  return Math.max(0, Math.trunc(value)).toLocaleString("ru-RU").replace(/[\u00a0\u202f]/g, " ");
}

export function cloudPointCoverage(cloud: CloudPointMetadata) {
  const sourcePointCount = Number.isFinite(cloud.point_count) ? Math.max(0, cloud.point_count) : 0;
  const storedPointCount = Number.isFinite(cloud.ingested_count) ? Math.max(0, cloud.ingested_count) : 0;
  const sampled = cloud.decimated === true || cloud.metadata?.decimated === true || storedPointCount < sourcePointCount;
  return {
    sourcePointCount,
    storedPointCount,
    sampled,
    label: `${countLabel(storedPointCount)} / ${countLabel(sourcePointCount)}`,
  };
}

export function scannerModelLabel(cloud: { metadata?: Record<string, any> } | null | undefined): string {
  const metadata = cloud?.metadata || {};
  const sensor = metadata.sensor && typeof metadata.sensor === "object" ? metadata.sensor : {};
  const model = metadata.scanner_model || metadata.sensor_model || metadata.device_model || sensor.model || sensor.name;
  return typeof model === "string" && model.trim() ? model.trim() : "Модель сканера не указана";
}

export function progressPercent(progress: number | null | undefined): number | null {
  if (typeof progress !== "number" || !Number.isFinite(progress)) return null;
  return Math.round(Math.min(1, Math.max(0, progress)) * 100);
}

export type PointColorMode = "rgb" | "height" | "intensity" | "normals" | "error";

export function canRenderPointColorMode(
  mode: PointColorMode,
  cloud: { has_color?: boolean } | null | undefined,
): boolean {
  if (mode === "height") return Boolean(cloud);
  if (mode === "rgb") return cloud?.has_color === true;
  // The viewer currently receives XYZ/RGB only; other modes would silently
  // fall back to height colors even if the cloud metadata advertises a field.
  return false;
}

export function resolvePointColorMode(
  mode: PointColorMode,
  cloud: { has_color?: boolean } | null | undefined,
): PointColorMode {
  return canRenderPointColorMode(mode, cloud) ? mode : "height";
}

export function cameraViewFromLabel(label: string | undefined): "top" | "front" | "right" | "iso" | "fit" | null {
  const normalized = label?.trim().toLowerCase() || "";
  if (normalized.startsWith("top")) return "top";
  if (normalized.startsWith("front")) return "front";
  if (normalized.startsWith("right")) return "right";
  if (normalized.includes("iso")) return "iso";
  if (normalized === "fit") return "fit";
  return null;
}
