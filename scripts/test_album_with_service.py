import json
from pathlib import Path
from scan2bim.services import list_elements
from scan2bim.cad.spds_full_set import generate_full_spds_album

cloud_id = 'workshop_cloud'
elements = list_elements(cloud_id)
print(f"Loaded {len(elements)} parsed elements from list_elements")
cols = [e for e in elements if e.get('class_name') == 'column']
print(f"Columns: {len(cols)}")
sample_col = cols[0]
print("Sample col keys:", sample_col.keys())
print("Sample col geom:", sample_col.get('geometry'))

out_dir = Path("data/output/test_spds_album")
out_dir.mkdir(parents=True, exist_ok=True)

manifest = generate_full_spds_album(
    elements=elements,
    output_dir=out_dir,
    project_title="Производственный корпус цеха (1.rcs + 2.rcs)",
)

print("Manifest generated successfully!")
print("Sheets in manifest:", len(manifest.get("sheets", [])))
for s in manifest.get("sheets", []):
    print(f"  - Sheet {s.get('num')}: {s.get('name')} | dxf: {s.get('dxf_path')} | pdf: {s.get('pdf_path')}")

print("\nFiles written on disk:")
for f in sorted(out_dir.iterdir()):
    print(f"  {f.name:45s} ({f.stat().st_size:,} bytes)")
