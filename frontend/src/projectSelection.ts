import type { Project } from "./types";

/** Prefer the user's saved project; on a fresh profile open the most populated project. */
export function selectInitialProject(
  projects: Project[],
  preferredProjectId?: string,
): Project | null {
  if (projects.length === 0) return null;
  const preferred = preferredProjectId
    ? projects.find((project) => project.id === preferredProjectId)
    : undefined;
  if (preferred) return preferred;

  return projects.reduce((best, candidate) => {
    const bestCount = Number.isFinite(best.cloud_count) ? best.cloud_count! : -1;
    const candidateCount = Number.isFinite(candidate.cloud_count) ? candidate.cloud_count! : -1;
    return candidateCount > bestCount ? candidate : best;
  });
}
