/** Counts completed viewer render-loop frames in rolling one-second windows. */
export class RenderFpsSampler {
  private windowStartedAt: number | null = null;
  private frameCount = 0;

  sample(timestampMs: number): number | null {
    if (!Number.isFinite(timestampMs)) return null;
    if (this.windowStartedAt === null || timestampMs < this.windowStartedAt) {
      this.windowStartedAt = timestampMs;
      this.frameCount = 0;
      return null;
    }

    this.frameCount += 1;
    const elapsedMs = timestampMs - this.windowStartedAt;
    if (elapsedMs < 1000) return null;

    const fps = Math.round((this.frameCount * 1000) / elapsedMs);
    this.windowStartedAt = timestampMs;
    this.frameCount = 0;
    return fps;
  }
}
