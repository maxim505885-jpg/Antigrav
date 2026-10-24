import type { Element } from "./types";

export interface StudioLayerVisibility {
  aiStructures: boolean;
  bimModel: boolean;
}

const confirmedReviewStatuses = new Set(["confirmed", "corrected"]);
const hiddenReviewStatuses = new Set(["rejected", "invalidated"]);

export function isStudioLayerVisible(available: boolean, enabled: boolean): boolean {
  return available && enabled;
}

/** Keep unreviewed recognition hypotheses separate from the reviewed BIM overlay. */
export function selectStudioOverlayElements(
  elements: Element[],
  visibility: StudioLayerVisibility,
): Element[] {
  if (!visibility.aiStructures && !visibility.bimModel) return [];

  return elements.filter((element) => {
    if (hiddenReviewStatuses.has(element.review_status)) return false;
    if (visibility.aiStructures && element.review_status === "unreviewed") return true;
    return visibility.bimModel && confirmedReviewStatuses.has(element.review_status);
  });
}
