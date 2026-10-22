from pathlib import Path

p = Path("backend/scan2bim/cad/spds_full_set.py")
content = p.read_text(encoding="utf-8")

# 1. Add validator import
import_code = "from ..recognition.column_validator import WorkshopColumnValidator\n"
if "WorkshopColumnValidator" not in content:
    target = "from .spds_tables import draw_spds_specification_table\n"
    content = content.replace(target, target + import_code, 1)

# 2. Integrate validator in generate_sheet_1_columns_plan
target_func = """def generate_sheet_1_columns_plan(aligned: dict[str, Any], out_dxf: str | Path, out_pdf: str | Path) -> tuple[Path, Path]:
    elements = aligned.get("elements", [])
    columns = [element for element in elements if element.get("class_name") == "column"]"""

replace_func = """def generate_sheet_1_columns_plan(aligned: dict[str, Any], out_dxf: str | Path, out_pdf: str | Path) -> tuple[Path, Path]:
    elements = aligned.get("elements", [])
    raw_columns = [element for element in elements if element.get("class_name") == "column"]
    
    # Экспертная валидация Агента-Конструктора: исключаем трубы, стойки оборудования и мусор
    validator = WorkshopColumnValidator()
    x_bays = aligned.get("x_bays") or []
    y_spans = aligned.get("y_spans") or []
    columns, rejected = validator.filter_column_candidates(raw_columns, known_x_bays=x_bays, known_y_spans=y_spans)
    if not columns and raw_columns:
        columns = raw_columns  # fallback if grid is not established yet"""

if target_func in content:
    content = content.replace(target_func, replace_func, 1)
    print("Integrated WorkshopColumnValidator in generate_sheet_1_columns_plan!")
else:
    print("target_func not found directly!")

p.write_text(content, encoding="utf-8")
print("Saved spds_full_set.py!")
