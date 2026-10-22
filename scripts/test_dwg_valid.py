import subprocess
from pathlib import Path

accore = r"C:\Program Files\Autodesk\AutoCAD 2026\accoreconsole.exe"
temp_work = Path(r"C:\Users\maxim\.gemini\antigravity\scratch\dwg_convert")
scr = temp_work / "test_check.scr"
dwg = temp_work / "01_plan_kolonn_SPDS.dwg"

script = f'_OPEN "{dwg.as_posix()}"\n_QSAVE\n_QUIT\n'
scr.write_text(script, encoding="utf-8")
res = subprocess.run([accore, "/s", str(scr)], capture_output=True, text=True)
print("Returncode:", res.returncode)
print("DWG size after QSAVE:", dwg.stat().st_size)
