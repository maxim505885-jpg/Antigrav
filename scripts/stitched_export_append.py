def export_stitched_cloud(
    stations_data: list[dict[str, Any]],
    output_path: Path,
) -> Path:
    """Apply SE(3) transformation to all stations and save unified point cloud (PLY format)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    all_points = []
    all_colors = []

    for st in stations_data:
        pts = np.asarray(st["points"], dtype=np.float32)
        mat = np.asarray(st.get("matrix_4x4", np.eye(4)), dtype=np.float32)

        # Apply transformation: R * pts + t
        r = mat[:3, :3]
        t = mat[:3, 3]
        transformed_pts = (r @ pts.T).T + t
        all_points.append(transformed_pts)

        if "colors" in st and st["colors"] is not None and len(st["colors"]) == len(pts):
            all_colors.append(np.asarray(st["colors"], dtype=np.uint8))
        else:
            # Default gray color
            all_colors.append(np.full((len(pts), 3), 200, dtype=np.uint8))

    merged_pts = np.vstack(all_points)
    merged_cols = np.vstack(all_colors)

    # Write clean binary PLY
    header = f"""ply
format binary_little_endian 1.0
element vertex {len(merged_pts)}
property float x
property float y
property float z
property uchar red
property uchar green
property uchar blue
end_header
"""
    with open(output_path, "wb") as f:
        f.write(header.encode("ascii"))
        # Structured array for fast binary write
        vertex_dtype = np.dtype([
            ("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
            ("red", "u1"), ("green", "u1"), ("blue", "u1"),
        ])
        vertex_data = np.empty(len(merged_pts), dtype=vertex_dtype)
        vertex_data["x"] = merged_pts[:, 0]
        vertex_data["y"] = merged_pts[:, 1]
        vertex_data["z"] = merged_pts[:, 2]
        vertex_data["red"] = merged_cols[:, 0]
        vertex_data["green"] = merged_cols[:, 1]
        vertex_data["blue"] = merged_cols[:, 2]
        f.write(vertex_data.tobytes())

    return output_path
