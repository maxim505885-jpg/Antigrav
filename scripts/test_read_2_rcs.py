import sys
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))

from scan2bim.formats.rcs_native import extract_rcs_native

p2 = Path(r"C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\2.rcs")
print(f"Path: {p2}, exists: {p2.exists()}, size: {p2.stat().st_size / (1024*1024*1024):.2f} GB")

out_tmp = Path("data/.tmp/test_2_rcs")
out_tmp.mkdir(parents=True, exist_ok=True)

try:
    print("Trying extract_rcs_native on 2.rcs (header / metadata pass)...")
    res = extract_rcs_native(p2, out_tmp)
    print("Result:", res)
except Exception as e:
    print("Extraction error:", type(e), e)
