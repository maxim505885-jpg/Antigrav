import sys
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))

from scan2bim.pipeline_single_pass import SinglePassWorkshopEngine

cloud_file = Path("data/projects/3f6321f10c9145db909ec27b1c2ba044/clouds/2621e5a320df49949d04aa1b7399539e/positions.npy")
engine = SinglePassWorkshopEngine(output_root="data/output/single_pass_release")

res = engine.execute_pipeline(cloud_file, project_title="Производственный цех 1.rcs (40 млн точек)")
print("\nРЕЗУЛЬТАТ ОДНОПРОХОДНОГО ПАЙПЛАЙНА:")
for k, v in res.items():
    print(f"  {k}: {v}")
