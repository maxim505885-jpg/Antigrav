/** Apply a source-local → target-local rigid transform to interleaved XYZ positions. */
export function decodeRegistrationPreviewPositions(buffer: ArrayBuffer, maxPoints: number): Float32Array {
  if (!Number.isInteger(maxPoints) || maxPoints < 1) throw new Error("Preview point limit must be a positive integer");
  if (buffer.byteLength === 0 || buffer.byteLength % 15 !== 0) throw new Error("Preview point buffer must contain 15-byte records");
  const view = new DataView(buffer);
  const sourceCount = buffer.byteLength / 15;
  const stride = Math.max(1, Math.ceil(sourceCount / maxPoints));
  const previewCount = Math.ceil(sourceCount / stride);
  const positions = new Float32Array(previewCount * 3);
  for (let sourceIndex = 0, targetIndex = 0; sourceIndex < sourceCount; sourceIndex += stride, targetIndex += 1) {
    const offset = sourceIndex * 15;
    positions[targetIndex * 3] = view.getFloat32(offset, true);
    positions[targetIndex * 3 + 1] = view.getFloat32(offset + 4, true);
    positions[targetIndex * 3 + 2] = view.getFloat32(offset + 8, true);
  }
  return positions;
}

export function transformRegistrationPreviewPositions(
  positions: Float32Array,
  matrix: number[][],
): Float32Array {
  if (positions.length % 3 !== 0) throw new Error("Preview positions must contain XYZ triplets");
  for (const value of positions) if (!Number.isFinite(value)) throw new Error("Preview positions must be finite");
  if (matrix.length !== 4 || matrix.some((row) => row.length !== 4 || row.some((value) => !Number.isFinite(value)))) {
    throw new Error("Registration preview requires a finite 4×4 transform");
  }
  if (matrix[3][0] !== 0 || matrix[3][1] !== 0 || matrix[3][2] !== 0 || matrix[3][3] !== 1) {
    throw new Error("Registration preview requires an affine rigid transform");
  }
  const transformed = new Float32Array(positions.length);
  for (let i = 0; i < positions.length; i += 3) {
    const x = positions[i];
    const y = positions[i + 1];
    const z = positions[i + 2];
    transformed[i] = matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z + matrix[0][3];
    transformed[i + 1] = matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z + matrix[1][3];
    transformed[i + 2] = matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z + matrix[2][3];
  }
  return transformed;
}
