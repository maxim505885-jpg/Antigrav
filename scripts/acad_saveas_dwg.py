import win32com.client
from pathlib import Path
import time

src_dir = Path(r"C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\intelligent-scan-to-bim\data\output\workshop_release\spds_album\clean_dwg_ready").resolve()
acad = win32com.client.Dispatch("AutoCAD.Application")
doc = acad.ActiveDocument

sheets = [
    "01_plan_kolonn_SPDS",
    "02_plan_podkranovyh_balok_SPDS",
    "03_razrez_ceha_1-1_SPDS",
    "04_shema_ferm_i_svyazei_SPDS",
    "05_ispolnitelnaya_shema_otkloneniy_SPDS",
]

for s in sheets:
    dxf_p = (src_dir / f"{s}.dxf").resolve()
    dwg_p = (src_dir / f"{s}.dwg").resolve()
    if dwg_p.exists():
        try:
            dwg_p.unlink()
        except Exception:
            pass

    cmd = f'._DXFIN "{dxf_p.as_posix()}"\n._ZOOM _E\n._SAVEAS 2018 "{dwg_p.as_posix()}"\n'
    doc.SendCommand(cmd)
    time.sleep(2)
    print(f"Sent {s}, dwg exists: {dwg_p.exists()}")
