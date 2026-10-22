from pathlib import Path

p = Path("backend/scan2bim/cad/spds_full_set.py")
content = p.read_text(encoding="utf-8")

# remove top import
if content.startswith("from .spds_tables import draw_spds_specification_table\n"):
    content = content[len("from .spds_tables import draw_spds_specification_table\n"):]

# place it after future annotations
target = "from __future__ import annotations\n"
replacement = "from __future__ import annotations\n\nfrom .spds_tables import draw_spds_specification_table\n"

if target in content and "from .spds_tables" not in content:
    content = content.replace(target, replacement, 1)

p.write_text(content, encoding="utf-8")
print("Fixed future annotations order in spds_full_set.py!")
