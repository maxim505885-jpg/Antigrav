export type RegistrationOutcomeState =
  | "not_converged"
  | "no_residual"
  | "above_threshold"
  | "review_required";

export interface RegistrationOutcomeInput {
  converged: boolean;
  rmse_mm: number | null;
}

export interface RegistrationOutcome {
  state: RegistrationOutcomeState;
  label: string;
  detail: string;
}

/** Present ICP diagnostics without equating optimizer convergence to survey accuracy. */
export function registrationOutcome(result: RegistrationOutcomeInput): RegistrationOutcome {
  if (!result.converged) {
    return {
      state: "not_converged",
      label: "Не сошлось",
      detail: "Остаток ICP не является оценкой точности регистрации.",
    };
  }
  if (result.rmse_mm === null || !Number.isFinite(result.rmse_mm) || result.rmse_mm < 0) {
    return {
      state: "no_residual",
      label: "Невязка не вычислена",
      detail: "Недостаточно допустимых соответствий; матрицу нельзя принимать.",
    };
  }
  if (result.rmse_mm > 10) {
    return {
      state: "above_threshold",
      label: "Остаток выше 10 мм",
      detail: "Нужна проверка начального положения и перекрытия станций.",
    };
  }
  return {
    state: "review_required",
    label: "Расчёт сошёлся · требуется независимая проверка",
    detail: "ICP RMSE описывает только подобранные соответствия, не независимую точность съёмки.",
  };
}
