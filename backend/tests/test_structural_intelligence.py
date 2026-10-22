import sys
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))

import json
from scan2bim.recognition.structural_intelligence import StructuralWorkshopClassifier

# Test classifier
classifier = StructuralWorkshopClassifier(bay_step_m=6.0, grid_tolerance_m=1.0, min_column_height_m=4.5)

raw_candidates = [
    # 1. Real column on grid
    {"id": "col_1", "geometry": {"center": [-60.02, -4.78, 2.0], "sizes": {"height": 9.5}}},
    # 2. Pipe/clutter in aisle (cy = 0.0)
    {"id": "clutter_pipe", "geometry": {"center": [-60.0, 0.5, 2.0], "sizes": {"height": 8.0}}},
    # 3. Machine post (short height)
    {"id": "machine_post", "geometry": {"center": [-60.0, -4.8, 0.5], "sizes": {"height": 1.2}}},
]

known_x_bays = [-66.0, -60.0, -54.0]
known_y_rows = {"А": -17.5, "Б": -4.8, "В": 7.5, "Г": 20.5}

res = classifier.classify_and_regularize(raw_candidates, known_x_bays, known_y_rows)
assert len(res) == 1, f"Expected 1 column, got {len(res)}"
assert res[0]["id"] == "col_1"
assert res[0]["mark"] == "К-Б2"
assert res[0]["type"] == "К-2 (ступенчатая средняя)"
print("Structural Intelligence Classifier unit test: 100% PASSED!")
