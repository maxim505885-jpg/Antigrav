from pathlib import Path

p = Path("backend/scan2bim/api/desktop.py")
content = p.read_text(encoding="utf-8")

# 1. Add REVIT_PATH
revit_decl = 'REVIT_PATH = Path(r"C:\\Program Files\\Autodesk\\Revit 2027\\Revit.exe")\n'
if "REVIT_PATH" not in content:
    target = 'RECAP_PATH = Path(r"C:\\Program Files\\Autodesk\\Autodesk ReCap\\ReCap.exe")'
    content = content.replace(target, target + "\n" + revit_decl, 1)

# 2. Update status response
old_status = """    return {
        "platform": sys.platform,
        "autocad_available": AUTOCAD_PATH.is_file(),
        "autocad_path": str(AUTOCAD_PATH) if AUTOCAD_PATH.is_file() else None,
        "recap_available": RECAP_PATH.is_file(),
        "recap_path": str(RECAP_PATH) if RECAP_PATH.is_file() else None,
    }"""

new_status = """    return {
        "platform": sys.platform,
        "autocad_available": AUTOCAD_PATH.is_file(),
        "autocad_path": str(AUTOCAD_PATH) if AUTOCAD_PATH.is_file() else None,
        "recap_available": RECAP_PATH.is_file(),
        "recap_path": str(RECAP_PATH) if RECAP_PATH.is_file() else None,
        "revit_available": REVIT_PATH.is_file(),
        "revit_path": str(REVIT_PATH) if REVIT_PATH.is_file() else None,
    }"""

content = content.replace(old_status, new_status, 1)

# 3. Add open_revit endpoint
open_revit_func = """
@router.post("/open-revit")
def open_revit(payload: OpenPathRequest | None = None) -> dict[str, Any]:
    \"\"\"Open Autodesk Revit 2027, optionally loading a specified RVT or IFC file.\"\"\"
    if not REVIT_PATH.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Autodesk Revit 2027 не найден по стандартному пути: {REVIT_PATH}",
        )
    cmd = [str(REVIT_PATH)]
    if payload and payload.path:
        target_path = Path(payload.path).resolve()
        if target_path.exists():
            cmd.append(str(target_path))

    subprocess.Popen(cmd)
    return {"status": "ok", "app": "Autodesk Revit 2027", "command": cmd}
"""

if "/open-revit" not in content:
    content += open_revit_func

p.write_text(content, encoding="utf-8")
print("Added Revit 2027 integration to desktop.py!")
