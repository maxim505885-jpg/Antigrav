import sys
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))

import json
import numpy as np
from scan2bim.recognition.structural_fitting import extract_actual_workshop_structural_members

cloud_dir = Path("data/projects/3f6321f10c9145db909ec27b1c2ba044/clouds/2621e5a320df49949d04aa1b7399539e")
pos = np.load(cloud_dir / "positions.npy", mmap_mode="r")

print(f"Запуск извлечения фактических осей подкрановых балок и ферм из 40,000,000 точек...")
res = extract_actual_workshop_structural_members(pos, rotation_deg=-10.23)

print("\n--- РАСПОЗНАННЫЕ ПОДКРАНОВЫЕ ПУТИ ---")
for r in res["crane_rails"]:
    print(f"Рельс Y={r['y_local_m']}м, Z={r['z_local_m']}м | длина {r['length_m']}м (от X={r['span_x_start_m']} до {r['span_x_end_m']}) | {r['point_count']:,} точек")

print(f"\n--- РАСПОЗНАННЫЕ ПЛОСКОСТИ ФЕРМ КРОВЛИ (всего {len(res['trusses'])} ферм) ---")
for t in res["trusses"][:10]:
    print(f"Ферма на X={t['x_local_m']}м | отметка Z=[{t['z_bottom_m']} .. {t['z_top_m']}] | пролет {t['span_length_m']}м | {t['point_count']:,} точек")
if len(res["trusses"]) > 10:
    print(f"... и еще {len(res['trusses']) - 10} ферм вдоль цеха.")

out_json = Path("data/output/workshop_release/fitted_structural_members.json")
out_json.parent.mkdir(parents=True, exist_ok=True)
out_json.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\nРезультат сохранен в файл: {out_json}")
