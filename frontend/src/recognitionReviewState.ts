export type IndependentReviewState = "labeled" | "unknown" | "excluded" | "pending";

const LABELS: Record<IndependentReviewState, string> = {
  labeled: "✓ Размечено",
  unknown: "? Неизвестно",
  excluded: "Исключено",
  pending: "Ожидает независимой проверки",
};

export function recognitionReviewState(state: string | null | undefined): {
  state: IndependentReviewState;
  label: string;
} {
  const normalized: IndependentReviewState = state === "labeled" || state === "unknown" || state === "excluded"
    ? state
    : "pending";
  return { state: normalized, label: LABELS[normalized] };
}
