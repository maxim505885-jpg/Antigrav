from pathlib import Path

p = Path("backend/scan2bim/registration/stitching.py")
content = p.read_text(encoding="utf-8")

old_code = """        "stations": [
            {
                "station_id": s["id"],
                "file_path": str(s.get("path", "")),
                "point_count": int(s.get("point_count", 0)),
                "matrix_4x4": s.get("matrix_4x4", np.eye(4).tolist()),
                "rmse_mm": float(s.get("rmse_mm", 0.0)),
            }
            for s in stations
        ],"""

new_code = """        "stations": [
            {
                "station_id": s.get("id") or s.get("station_id") or f"station_{idx+1}",
                "file_path": str(s.get("path", "")),
                "point_count": int(s.get("point_count", 0)),
                "matrix_4x4": s.get("matrix_4x4", np.eye(4).tolist()),
                "rmse_mm": float(s.get("rmse_mm", 0.0)),
            }
            for idx, s in enumerate(stations)
        ],"""

if old_code in content:
    p.write_text(content.replace(old_code, new_code, 1), encoding="utf-8")
    print("Fixed station_id handling in stitching.py!")
else:
    print("Pattern not matched!")
