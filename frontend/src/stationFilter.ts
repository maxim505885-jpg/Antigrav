import type { Cloud } from "./types.ts";

export function filterRegistrationStations(stations: readonly Cloud[], query: string): Cloud[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  if (!normalizedQuery) return [...stations];

  return stations.filter((station) =>
    `${station.name} ${station.id} ${station.source_format} ${station.source_path}`
      .toLocaleLowerCase()
      .includes(normalizedQuery),
  );
}
