import subprocess
import shutil
from pathlib import Path

sample_dwg = Path(r"C:\Program Files\Autodesk\AutoCAD 2026\Express\brkline.dwg")
accore = r"C:\Program Files\Autodesk\AutoCAD 2026\accoreconsole.exe"

test_dir = Path(r"C:\Users\maxim\.gemini\antigravity\scratch\test_dwg_gen")
test_dir.mkdir(parents=True, exist_ok=True)

test_input = test_dir / "input.dwg"
shutil.copy2(sample_dwg, test_input)

test_dxf = Path(r"C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\intelligent-scan-to-bim\data\output\single_pass_release\spds_album\01_plan_kolonn_SPDS.dxf").resolve()
test_output_dwg = test_dir / "01_plan_kolonn_SPDS.dwg"

if test_output_dwg.exists():
    test_output_dwg.unlink()

# AutoCAD script with clean ASCII commands
scr_content = f'''(command "_.ERASE" "ALL" "")
(command "_.-INSERT" "{test_dxf.as_posix()}" "0,0,0" "1" "1" "0")
(command "_.EXPLODE" (entlast))
(command "_.ZOOM" "_E")
(command "_.SAVEAS" "2018" "{test_output_dwg.as_posix()}")
(command "_.QUIT" "_Y")
'''

scr_file = test_dir / "make_dwg.scr"
scr_file.write_text(scr_content, encoding="utf-8")

cmd = [
    accore,
    "/i", str(test_input),
    "/s", str(scr_file)
]

print("Running accoreconsole with input.dwg...")
res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
print("Returncode:", res.returncode)
if test_output_dwg.exists():
    print(f"SUCCESS! Created DWG: {test_output_dwg} ({test_output_dwg.stat().st_size / 1024:.1f} KB)")
else:
    print("FAILED to create DWG.")
    print("Output tail:\n", res.stdout[-500:])
