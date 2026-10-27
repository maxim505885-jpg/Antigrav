export function detailText(error: any): string {
  const detail = error?.detail;
  if (detail?.detail) {
    if (typeof detail.detail === "string") return detail.detail;
    const summary = detail.detail.summary;
    const message = detail.detail.message;
    if (typeof summary === "string" && typeof message === "string") return `${summary} ${message}`;
    if (typeof summary === "string") return summary;
    return JSON.stringify(detail.detail);
  }
  if (typeof detail === "string") return detail;
  return error?.message || String(error);
}
