const reviewerByCloud = new Map<string, string>();

export function annotationReviewerFor(cloudId: string, savedReviewer?: string | null): string {
  const saved = savedReviewer?.trim();
  if (saved) return saved;
  return reviewerByCloud.get(cloudId) || "";
}

export function rememberAnnotationReviewer(cloudId: string, reviewer: string): void {
  const normalized = reviewer.trim();
  if (normalized) reviewerByCloud.set(cloudId, normalized);
  else reviewerByCloud.delete(cloudId);
}

export function resetAnnotationReviewersForTests(): void {
  reviewerByCloud.clear();
}
