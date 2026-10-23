from pathlib import Path
from scan2bim.db import rows
from scan2bim.cad.spds_full_set import generate_full_spds_album

cloud_id = 'workshop_cloud'
elements = rows("SELECT * FROM elements WHERE cloud_id = ?", (cloud_id,))
print(f"Loaded {len(elements)} elements")

out_dir = Path("data/output/test_spds_album")
out_dir.mkdir(parents=True, exist_ok=True)

manifest = generate_full_spds_album(
    elements=elements,
    output_dir=out_dir,
    project_title="Тестовый цех",
)

print("Manifest sheets count:", len(manifest.get("sheets", [])))
for s in manifest.get("sheets", []):
    print(f"Sheet {s.get('num')}: name={s.get('name')} dxf={s.get('dxf_path')} pdf={s.get('pdf_path')}")

print("\nFiles in out_dir:")
for f in out_dir.iterdir():
    print(f"  {f.name} ({f.stat().st_size:,} bytes)")
