import sys
import json
from pathlib import Path

meta_file = Path("data/projects/3f6321f10c9145db909ec27b1c2ba044/clouds/2621e5a320df49949d04aa1b7399539e/meta.json")
if meta_file.exists():
    print(json.dumps(json.loads(meta_file.read_text(encoding="utf-8")), indent=2))
else:
    print("meta.json not found")
