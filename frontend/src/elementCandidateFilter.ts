import type { Element } from "./types";

export const elementClassLabels: Record<string, string> = {
  beam: "Балка", brace: "Связь", column: "Колонна", truss: "Ферма",
  wall: "Стена", slab: "Плита", roof: "Кровля", stair: "Лестница",
  opening: "Проём", pipe: "Трубопровод", duct: "Воздуховод",
};

/** Filter review candidates by ID, class code or the role label shown in the table. */
export function filterElementCandidates(
  elements: Element[],
  query: string,
  className: string,
): Element[] {
  const normalizedQuery = query.trim().toLocaleLowerCase("ru-RU");
  return elements.filter((element) => {
    if (className !== "all" && element.class_name !== className) return false;
    if (!normalizedQuery) return true;
    const searchable = [
      element.id,
      element.class_name,
      elementClassLabels[element.class_name],
      element.dimensions?.role,
      element.dimensions?.role_label,
    ].filter((value) => typeof value === "string").join(" ").toLocaleLowerCase("ru-RU");
    return searchable.includes(normalizedQuery);
  });
}
