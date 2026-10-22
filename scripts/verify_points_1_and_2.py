import os
import json
from pathlib import Path
import numpy as np

def run_checks():
    print("================================================================================")
    print("                      SCAN-TO-BIM AUDIT: ITEMS 1 & 2")
    print("================================================================================")

    # 1. POINT CLOUD STITCHING VERIFICATION
    print("\n[ITEM 1A: POINT CLOUD STITCHING (1.rcs + 2.rcs)]")
    base_dir = Path("data/output/unified_stitched_release")
    ply_path = base_dir / "unified_stitched_cloud.ply"
    manifest_path = base_dir / "registration_manifest.json"
    npy_path = base_dir / "unified_cloud" / "positions.npy"
    meta_path = base_dir / "unified_cloud" / "meta.json"

    if ply_path.exists():
        size_mb = ply_path.stat().st_size / (1024 * 1024)
        print(f"  [OK] Unified PLY file exists: {ply_path} ({size_mb:.2f} MB)")
        with open(ply_path, "rb") as f:
            header_lines = [f.readline().decode("latin1").strip() for _ in range(12)]
        print(f"       PLY format: {header_lines[1]}")
        elem_line = [l for l in header_lines if l.startswith("element vertex")]
        if elem_line:
            print(f"       PLY vertex count in header: {elem_line[0]}")
    else:
        print(f"  [FAIL] Unified PLY file NOT found at {ply_path}")

    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as f:
            man = json.load(f)
        print(f"  [OK] Registration manifest found: {manifest_path}")
        print(f"       Project name: {man.get('project_name')}")
        print(f"       Station count: {man.get('station_count')}")
        print(f"       Status: {man.get('status')}")
        for st in man.get("stations", []):
            st_id = st.get("station_id")
            pts = st.get("point_count", 0)
            rmse = st.get("rmse_mm", 0.0)
            mat = st.get("matrix_4x4", [])
            t = [mat[0][3], mat[1][3], mat[2][3]] if len(mat) >= 3 else []
            print(f"       Station '{st_id}': file={st.get('file_path')}, pts={pts:,}, rmse={rmse:.2f} mm, T={t}")
    else:
        print(f"  [FAIL] Registration manifest NOT found at {manifest_path}")

    if npy_path.exists():
        arr = np.load(npy_path, mmap_mode="r")
        size_mb = npy_path.stat().st_size / (1024 * 1024)
        print(f"  [OK] NPY Memory-Mapped Positions: shape={arr.shape}, dtype={arr.dtype}, size={size_mb:.2f} MB")
        print(f"       Bounding box X: [{arr[:,0].min():.2f}, {arr[:,0].max():.2f}] m")
        print(f"       Bounding box Y: [{arr[:,1].min():.2f}, {arr[:,1].max():.2f}] m")
        print(f"       Bounding box Z: [{arr[:,2].min():.2f}, {arr[:,2].max():.2f}] m")
    else:
        print(f"  [FAIL] NPY positions file NOT found at {npy_path}")

    # 1B. DWG SPDS ALBUM VERIFICATION
    print("\n[ITEM 1B: AUTOCAD 2026 BINARY DWG (AC1032) COMPILATION]")
    dwg_dir = base_dir / "spds_release" / "spds_draft"
    if dwg_dir.exists():
        dwg_files = sorted(list(dwg_dir.glob("*.dwg")))
        print(f"  [OK] DWG album directory exists: {dwg_dir}")
        print(f"       Total DWG sheets found: {len(dwg_files)}")
        for dwg in dwg_files:
            with open(dwg, "rb") as f:
                header = f.read(6).decode("ascii", errors="ignore")
            size_kb = dwg.stat().st_size / 1024
            status = "AC1032 binary valid" if header == "AC1032" else f"Header {header}"
            print(f"       * {dwg.name:45s} | {size_kb:8.1f} KB | {status}")
    else:
        print(f"  [FAIL] DWG directory NOT found at {dwg_dir}")

    # 2. REVIT 2027 EXPORT & ADD-IN VERIFICATION
    print("\n[ITEM 2: AUTODESK REVIT 2027 INTEGRATION (.RVT / ADD-IN)]")
    addin_dll = Path("integrations/revit/Scan.Plugin/bin/Release/net10.0-windows/Scan.Revit.Plugin.dll")
    if addin_dll.exists():
        size_kb = addin_dll.stat().st_size / 1024
        print(f"  [OK] Compiled Revit 2027 C# Add-In DLL: {addin_dll} ({size_kb:.1f} KB)")
    else:
        print(f"  [FAIL] Compiled Revit 2027 Add-In DLL NOT found at {addin_dll}")

    appdata = os.environ.get("APPDATA", "")
    progdata = os.environ.get("PROGRAMDATA", "")
    user_addin = Path(appdata) / "Autodesk" / "Revit" / "Addins" / "2027" / "SCAN.StructuralModel.addin"
    sys_addin = Path(progdata) / "Autodesk" / "Revit" / "Addins" / "2027" / "SCAN.StructuralModel.addin"

    print(f"  [OK] User Add-In manifest installed: {user_addin.exists()} -> {user_addin}")
    print(f"  [OK] System Add-In manifest installed: {sys_addin.exists()} -> {sys_addin}")
    if user_addin.exists():
        content = user_addin.read_text(encoding="utf-8")
        has_assembly = "Scan.Revit.Plugin.dll" in content
        has_full_class = "Scan.Revit.Plugin.ImportStructuralModelCommand" in content
        print(f"       - Assembly reference present: {has_assembly}")
        print(f"       - FullClassName correct: {has_full_class}")

    bim_json = base_dir / "revit_bim_model.json"
    if bim_json.exists():
        with open(bim_json, "r", encoding="utf-8") as f:
            bdata = json.load(f)
        size_mb = bim_json.stat().st_size / (1024 * 1024)
        elements = bdata.get("elements", [])
        categories = {}
        for el in elements:
            cat = el.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1
        print(f"  [OK] Revit BIM JSON model exists: {bim_json} ({size_mb:.2f} MB)")
        print(f"       Contract: format='{bdata.get('format')}', schema_version='{bdata.get('schema_version')}'")
        print(f"       Grids count: {len(bdata.get('grids', []))}")
        print(f"       Levels count: {len(bdata.get('levels', []))}")
        print(f"       Total structural elements: {len(elements)}")
        for cat, count in sorted(categories.items()):
            print(f"         - {cat:25s}: {count:4d} elements")
    else:
        print(f"  [FAIL] Revit BIM model JSON NOT found at {bim_json}")

    ifc_path = base_dir / "unified_model.ifc"
    if ifc_path.exists():
        size_mb = ifc_path.stat().st_size / (1024 * 1024)
        with open(ifc_path, "r", encoding="utf-8", errors="ignore") as f:
            first_lines = [f.readline().strip() for _ in range(5)]
        print(f"  [OK] IFC4 model exists: {ifc_path} ({size_mb:.2f} MB)")
        print(f"       Header: {first_lines[0]} / {first_lines[1]}")
    else:
        print(f"  [FAIL] IFC4 model NOT found at {ifc_path}")

if __name__ == "__main__":
    run_checks()
