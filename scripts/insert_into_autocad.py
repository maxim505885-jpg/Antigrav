import win32com.client
from pathlib import Path
import time

acad = win32com.client.Dispatch("AutoCAD.Application")
doc = acad.ActiveDocument

src_dir = Path(r"C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\intelligent-scan-to-bim\data\output\workshop_release\spds_album\autocad_compatible").resolve()
target_dir = Path(r"C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\intelligent-scan-to-bim\data\output\workshop_release\spds_album").resolve()

dxf_file = src_dir / "01_plan_kolonn_SPDS.dxf"
dwg_file = target_dir / "01_plan_kolonn_SPDS.dwg"

# Send LISP command to AutoCAD to insert DXF at 0,0, explode, zoom extents
lisp1 = f'(command "_.-INSERT" "{dxf_file.as_posix()}" "0,0,0" "1" "1" "0")\n'
lisp2 = '(command "_.EXPLODE" (entlast))\n'
lisp3 = '(command "_.ZOOM" "_E")\n'

doc.SendCommand(lisp1)
time.sleep(1)
doc.SendCommand(lisp2)
time.sleep(0.5)
doc.SendCommand(lisp3)
print("AutoCAD workspace populated directly with columns and grid!")
