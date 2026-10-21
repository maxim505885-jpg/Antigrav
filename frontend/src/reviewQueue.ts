export type ReviewFilter = "pending" | "conflicts" | "checked" | "rejected" | "all";
export type ReferenceFilter = "all" | "needs_reference" | "labeled" | "unknown" | "excluded";

type ReviewableElement = {
  review_status: string;
  dimensions?: Record<string, unknown>;
};

export function filterReviewElements<T extends ReviewableElement>(elements: T[], filter: ReviewFilter): T[] {
  switch (filter) {
    case "pending":
      return elements.filter((element) => element.review_status === "unreviewed");
    case "conflicts":
      return elements.filter((element) => {
        const conflicts = element.dimensions?.review_conflict_with;
        return element.review_status === "unreviewed" && Array.isArray(conflicts) && conflicts.length > 0;
      });
    case "checked":
      return elements.filter((element) => ["confirmed", "corrected"].includes(element.review_status));
    case "rejected":
      return elements.filter((element) => element.review_status === "rejected");
    case "all":
      return elements;
  }
}

type ReferenceElement = { id: string; class_name: string };

export function filterReferenceElements<T extends ReferenceElement>(
  elements: T[],
  filter: ReferenceFilter,
  states: Record<string, string>,
): T[] {
  return elements.filter((element) => {
    if (filter === "all") return true;
    if (element.class_name !== "column") return false;
    const state = states[element.id] || "pending";
    if (filter === "needs_reference") return state === "pending";
    return state === filter;
  });
}
