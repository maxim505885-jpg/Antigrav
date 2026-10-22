from pathlib import Path

p = Path("backend/scan2bim/registration/stitching.py")
content = p.read_text(encoding="utf-8")

old_code = """    t4x4 = np.eye(4, dtype=np.float64)
    t4x4[:3, :3] = current_r
    t4x4[:3, 3] = current_t

    return {
        "rotation": current_r.tolist(),
        "translation": current_t.tolist(),
        "matrix_4x4": t4x4.tolist(),
        "rmse_mm": round(float(prev_rmse * 1000.0), 3),
        "iterations": iteration + 1,
        "converged": converged,
    }"""

new_code = """    t4x4 = np.eye(4, dtype=np.float64)
    t4x4[:3, :3] = current_r
    t4x4[:3, 3] = current_t

    final_rmse = 0.0 if prev_rmse == float("inf") else round(float(prev_rmse * 1000.0), 3)

    return {
        "rotation": current_r.tolist(),
        "translation": current_t.tolist(),
        "matrix_4x4": t4x4.tolist(),
        "rmse_mm": final_rmse,
        "iterations": iteration + 1,
        "converged": converged,
    }"""

if old_code in content:
    p.write_text(content.replace(old_code, new_code, 1), encoding="utf-8")
    print("Fixed inf handling in stitching.py!")
else:
    print("Pattern not matched!")
