import subprocess
from pathlib import Path

accore = r"C:\Program Files\Autodesk\AutoCAD 2026\accoreconsole.exe"
src_dir = Path(r"C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\intelligent-scan-to-bim\data\output\workshop_release\spds_album\clean_dwg_ready")
temp_work = Path(r"C:\Users\maxim\.gemini\antigravity\scratch\dwg_convert2")
temp_work.mkdir(parents=True, exist_ok=True)

sheets = [
    "01_plan_kolonn_SPDS",
    "02_plan_podkranovyh_balok_SPDS",
    "03_razrez_ceha_1-1_SPDS",
    "04_shema_ferm_i_svyazei_SPDS",
    "05_ispolnitelnaya_shema_otkloneniy_SPDS",
]

for s in sheets:
    dxf_clean = (src_dir / f"{s}.dxf").resolve()
    dwg_out = (src_dir / f"{s}.dwg").resolve()
    scr = temp_work / f"{s}.scr"

    if dwg_out.exists():
        try:
            dwg_out.unlink()
        except Exception:
            pass

    script = (
        f'_DXFIN "{dxf_clean.as_posix()}"\n'
        f"_ZOOM _E\n"
        f"_SAVEAS\n"
        f"2018\n"
        f'"{dwg_out.as_posix()}"\n'
        f"_QUIT _Y\n"
    )
    scr.write_text(script, encoding="utf-8")
    res = subprocess.run([accore, "/s", str(scr)], capture_output=True, text=True, timeout=30)
    if dwg_out.exists():
        print(f"CLEAN DWG SUCCESS: {dwg_out.name} ({dwg_out.stat().st_size / 1024:.1f} KB)")
    else:
        print(f"FAILED {s}")
