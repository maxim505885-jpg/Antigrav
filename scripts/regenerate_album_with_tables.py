import sys
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))

import json
from scan2bim.cad.spds_full_set import _legacy_generate_full_spds_album

# Load project elements
db_dir = Path("data/output/workshop_release")
json_path = db_dir / "workshop_model.json"

elements = []
if json_path.exists():
    data = json.loads(json_path.read_text(encoding="utf-8"))
    elements = data.get("elements", [])
    print(f"Loaded {len(elements)} elements from workshop_model.json")

out_album_dir = Path("data/output/workshop_release/spds_album")
res = _legacy_generate_full_spds_album(elements, out_album_dir)
print("\n=== ОБНОВЛЕННЫЙ АЛЬБОМ РД СПДС (с официальными Спецификациями ГОСТ 21.501) ===")
for k, v in res.items():
    p = Path(v)
    print(f"{k}: {p.name} ({p.stat().st_size / 1024:.1f} KB)")
