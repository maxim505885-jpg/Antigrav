import type { Cloud } from "./types";

export function defaultRegistrationCloudIds(
  readyClouds: Cloud[],
  initialSourceCloudId?: string,
): { sourceId: string; targetId: string } {
  const rcsStations = readyClouds.filter((cloud) => cloud.source_format.toLowerCase() === "rcs");
  const workshopStations = rcsStations.filter((cloud) => /workshop/i.test(cloud.name || ""));
  const preferred = workshopStations.length >= 2
    ? workshopStations
    : rcsStations.length >= 2
      ? rcsStations
      : readyClouds;
  const sourceId = preferred.some((cloud) => cloud.id === initialSourceCloudId)
    ? initialSourceCloudId!
    : preferred[0]?.id || "";
  const targetId = preferred.find((cloud) => cloud.id !== sourceId)?.id || "";
  return { sourceId, targetId };
}
