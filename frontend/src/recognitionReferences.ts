import type { ElementAnnotationDataset, RecognitionEvaluationRequest } from "./api";

const ROLE_CLASSES: Record<string, readonly string[]> = {
  column: ["column"], crane_column: ["column"],
  beam: ["beam", "girder"], crane_girder: ["beam", "girder"],
  roof_beam: ["beam", "girder", "roof"], rail: ["beam", "girder"],
  floor_beam: ["beam", "girder", "slab"], purlin: ["beam", "girder", "roof"],
  truss_member: ["truss"], truss_top_chord: ["truss"], truss_bottom_chord: ["truss"],
  truss_post: ["truss"], truss_web: ["truss"], brace: ["brace", "truss"],
  pipe: ["pipe"], duct: ["duct"], cable_tray: ["duct"],
  other: ["wall", "column", "beam", "girder", "slab", "roof", "truss", "brace", "stair", "opening", "pipe", "duct", "equipment", "other"],
  unknown: ["wall", "column", "beam", "girder", "slab", "roof", "truss", "brace", "stair", "opening", "pipe", "duct", "equipment", "other"],
};

export function roleMatchesClass(className: string, roleLabel: string): boolean {
  return (ROLE_CLASSES[roleLabel] || []).includes(className);
}

export function roleOptionsForClass<T extends readonly [string, string]>(
  className: string,
  options: readonly T[],
): T[] {
  return options.filter(([role]) => roleMatchesClass(className, role));
}

export interface PhysicalReferenceDraft {
  physical_instance_id: string;
  class_name: string;
  role_label: string;
  min_x: string;
  min_y: string;
  min_z: string;
  max_x: string;
  max_y: string;
  max_z: string;
}

export interface RecognitionEvaluationMetadataDraft {
  reference_set_id: string;
  reference_kind: RecognitionEvaluationRequest["reference_kind"];
  annotator: string;
}

export function emptyPhysicalReferenceDraft(): PhysicalReferenceDraft {
  return {
    physical_instance_id: "", class_name: "", role_label: "",
    min_x: "", min_y: "", min_z: "", max_x: "", max_y: "", max_z: "",
  };
}

export function buildRecognitionEvaluationRequest(
  dataset: Pick<ElementAnnotationDataset, "source_snapshot_sha256">,
  metadata: RecognitionEvaluationMetadataDraft,
  drafts: PhysicalReferenceDraft[],
): RecognitionEvaluationRequest {
  const referenceSetId = metadata.reference_set_id.trim();
  const annotator = metadata.annotator.trim();
  if (!referenceSetId) throw new Error("Укажи идентификатор набора эталонов.");
  if (!annotator) throw new Error("Укажи разметчика.");
  if (drafts.length === 0) throw new Error("Добавь хотя бы один независимо измеренный физический эталон.");

  const physicalIds = new Set<string>();
  const referenceElements = drafts.map((draft, index) => {
    const physicalId = draft.physical_instance_id.trim();
    if (!physicalId) throw new Error(`Эталон ${index + 1}: укажи физический ID.`);
    if (physicalIds.has(physicalId)) throw new Error(`Физический ID «${physicalId}» повторяется.`);
    physicalIds.add(physicalId);
    if (!draft.class_name.trim()) throw new Error(`Эталон ${index + 1}: выбери независимый класс.`);
    if (draft.role_label.trim() && !roleMatchesClass(draft.class_name, draft.role_label.trim())) {
      throw new Error(`Эталон ${index + 1}: конструктивная роль не соответствует выбранному классу.`);
    }

    const rawCoordinates = [draft.min_x, draft.min_y, draft.min_z, draft.max_x, draft.max_y, draft.max_z];
    const coordinates = rawCoordinates.map((raw) => Number(raw.replace(",", ".")));
    if (rawCoordinates.some((raw) => raw.trim() === "") || coordinates.some((value) => !Number.isFinite(value))) {
      throw new Error(`Эталон ${index + 1}: координаты bbox должны быть конечными числами в метрах.`);
    }
    const [minX, minY, minZ, maxX, maxY, maxZ] = coordinates;
    const min = [minX, minY, minZ];
    const max = [maxX, maxY, maxZ];
    if (min.some((value, axis) => value >= max[axis])) {
      throw new Error(`Эталон ${index + 1}: min должен быть меньше max по каждой оси.`);
    }

    return {
      physical_instance_id: physicalId,
      class_name: draft.class_name,
      role_label: draft.role_label.trim() || null,
      bbox: { min: [minX, minY, minZ] as [number, number, number], max: [maxX, maxY, maxZ] as [number, number, number] },
    };
  });

  return {
    source_snapshot_sha256: dataset.source_snapshot_sha256,
    reference_set_id: referenceSetId,
    reference_origin: "independent_manual",
    reference_kind: metadata.reference_kind,
    annotator,
    iou_threshold: 0.5,
    reference_elements: referenceElements,
  };
}
