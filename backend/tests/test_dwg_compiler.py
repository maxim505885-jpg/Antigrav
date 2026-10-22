import sys
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))

from scan2bim.cad.dwg_compiler import convert_dxf_to_dwg_native, batch_convert_album_to_dwg

test_album_dir = Path("data/output/single_pass_release/spds_album")

print("Запуск пакетной компиляции всех чертежей альбома в бинарные DWG...")
dwg_files = batch_convert_album_to_dwg(test_album_dir)

print(f"\nВсего создано {len(dwg_files)} DWG файлов:")
for dwg in dwg_files:
    print(f"  - {dwg.name}: {dwg.stat().st_size / 1024:.1f} KB")

assert len(dwg_files) >= 5, "Ожидалось не менее 5 скомпилированных DWG чертежей"
print("\nТест автоматической DWG компиляции: 100% УСПЕШНО ПРОЙДЕН!")
