import subprocess
from pathlib import Path

def open_in_autocad(dxf_path: str | Path) -> bool:
    acad_exe = Path(r"C:\Program Files\Autodesk\AutoCAD 2026\acad.exe")
    if not acad_exe.is_file():
        return False
    dxf_path = Path(dxf_path).resolve()
    subprocess.Popen([str(acad_exe), str(dxf_path)])
    return True

def open_in_recap(project_path: str | Path | None = None) -> bool:
    recap_exe = Path(r"C:\Program Files\Autodesk\Autodesk ReCap\ReCap.exe")
    if not recap_exe.is_file():
        return False
    cmd = [str(recap_exe)]
    if project_path:
        cmd.append(str(Path(project_path).resolve()))
    subprocess.Popen(cmd)
    return True

def open_in_explorer(folder_or_file: str | Path) -> bool:
    target = Path(folder_or_file).resolve()
    if target.is_file():
        subprocess.Popen(["explorer.exe", f"/select,{target}"])
    else:
        subprocess.Popen(["explorer.exe", str(target)])
    return True

if __name__ == "__main__":
    print("Testing desktop integration functions...")
    sample_dxf = Path("data/output/workshop_release/spds_album/01_plan_kolonn_SPDS.dxf")
    print(f"Sample DXF exists: {sample_dxf.exists()}")
    print("Integration functions ready.")
