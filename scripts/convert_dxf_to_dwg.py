import subprocess
import shutil
from pathlib import Path

accore = r"C:\Program Files\Autodesk\AutoCAD 2026\accoreconsole.exe"
src_dir = Path(r"C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\intelligent-scan-to-bim\data\output\workshop_release\spds_album")

# Temporary short ascii path for script and processing to avoid codepage issues in AutoCAD console
temp_work = Path(r"C:\Users\maxim\.gemini\antigravity\scratch\dwg_convert")
temp_work.mkdir(parents=True, exist_ok=True)

sheets = [
    "01_plan_kolonn_SPDS",
    "02_plan_podkranovyh_balok_SPDS",
    "03_razrez_ceha_1-1_SPDS",
    "04_shema_ferm_i_svyazei_SPDS",
    "05_ispolnitelnaya_shema_otkloneniy_SPDS",
]

for s in sheets:
    dxf_orig = src_dir / f"{s}.dxf"
    dwg_target = src_dir / f"{s}.dwg"
    
    t_dxf = temp_work / f"{s}.dxf"
    t_dwg = temp_work / f"{s}.dwg"
    t_scr = temp_work / f"{s}.scr"

    shutil.copy2(dxf_orig, t_dxf)

    if t_dwg.exists():
        t_dwg.unlink()

    script = (
        f'_DXFIN "{t_dxf.as_posix()}"\n'
        f'_ZOOM _E\n'
        f'_SAVEAS\n'
        f'2018\n'
        f'"{t_dwg.as_posix()}"\n'
        f'_QUIT _Y\n'
    )
    t_scr.write_text(script, encoding="utf-8")

    cmd = [accore, "/s", str(t_scr)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    
    if t_dwg.exists():
        shutil.copy2(t_dwg, dwg_target)
        print(f"SUCCESS: {dwg_target.name} ({dwg_target.stat().st_size / 1024:.1f} KB)")
    else:
        print(f"FAILED {s}")
        print("OUT:", res.stdout[-300:])
