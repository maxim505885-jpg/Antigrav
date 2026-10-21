export type OrientedBoxDraft = {
  centerX: string;
  centerY: string;
  centerZ: string;
  length: string;
  thickness: string;
  height: string;
  rotationDegrees: string;
};

export type OrientedBoxGeometry = {
  kind: "oriented_box";
  center: [number, number, number];
  sizes: { length: number; thickness: number; height: number };
  rotation_z: number;
};

export function orientedBoxDraft(geometry: any): OrientedBoxDraft {
  const center = geometry?.center ?? [];
  const sizes = geometry?.sizes ?? {};
  const degrees = Number(geometry?.rotation_z ?? 0) * 180 / Math.PI;
  return {
    centerX: String(center[0] ?? ""),
    centerY: String(center[1] ?? ""),
    centerZ: String(center[2] ?? ""),
    length: String(sizes.length ?? ""),
    thickness: String(sizes.thickness ?? ""),
    height: String(sizes.height ?? ""),
    rotationDegrees: String(Number.isFinite(degrees) ? Number(degrees.toFixed(5)) : ""),
  };
}

export function buildOrientedBoxGeometry(draft: OrientedBoxDraft): OrientedBoxGeometry {
  const parse = (value: string) => value.trim() === "" ? Number.NaN : Number(value);
  const center = [draft.centerX, draft.centerY, draft.centerZ].map(parse);
  const length = parse(draft.length);
  const thickness = parse(draft.thickness);
  const height = parse(draft.height);
  const rotationDegrees = parse(draft.rotationDegrees);
  if (![...center, length, thickness, height].every(Number.isFinite)) {
    throw new Error("Введите конечные координаты и размеры элемента.");
  }
  if (length <= 0 || thickness <= 0 || height <= 0) {
    throw new Error("Размеры элемента должны быть больше нуля.");
  }
  if (!Number.isFinite(rotationDegrees)) {
    throw new Error("Введите конечный угол поворота.");
  }
  return {
    kind: "oriented_box",
    center: center as [number, number, number],
    sizes: { length, thickness, height },
    rotation_z: rotationDegrees * Math.PI / 180,
  };
}
