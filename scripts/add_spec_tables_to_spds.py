from pathlib import Path

p = Path("backend/scan2bim/cad/spds_full_set.py")
content = p.read_text(encoding="utf-8")

# 1. Add import
import_stmt = "from .spds_tables import draw_spds_specification_table"
if "from .spds_tables" not in content:
    content = "from .spds_tables import draw_spds_specification_table\n" + content
    print("Added import of draw_spds_specification_table")

# 2. Add table to Sheet 1 in _legacy_generate_sheet_1_columns_plan
target_s1 = """    draw_spds_title_block(
        msp,
        bottom_right_x=inner_box[2],
        bottom_right_y=inner_box[1],
        project_title=project_title,
        sheet_title="Схема расположения колонн на отм. 0.000",
        scale_factor=scale_factor,
        stage="Р",
        sheet_num=1,
        total_sheets=4,
    )"""

replace_s1 = """    draw_spds_title_block(
        msp,
        bottom_right_x=inner_box[2],
        bottom_right_y=inner_box[1],
        project_title=project_title,
        sheet_title="Схема расположения колонн на отм. 0.000",
        scale_factor=scale_factor,
        stage="Р",
        sheet_num=1,
        total_sheets=5,
    )

    # Таблица спецификации элементов по ГОСТ 21.501-2018 (Форма 7)
    spec_items_1 = [
        {"pos": "К-1", "designation": "Серия 1.424.1-5", "name": "Колонна К-1 средняя (двутавр)", "count": 140, "mass": 1850, "comment": ""},
        {"pos": "К-2", "designation": "Серия 1.424.1-5", "name": "Колонна К-2 крайняя / фахверк", "count": 93, "mass": 1420, "comment": ""},
    ]
    draw_spds_specification_table(
        msp,
        top_right_x=inner_box[2],
        top_right_y=inner_box[1] + (55.0 + len(spec_items_1) * 8.0 + 20.0) * (scale_factor / 1000.0),
        items=spec_items_1,
        scale_factor=scale_factor,
        title="Спецификация к схеме расположения колонн",
    )"""

if target_s1 in content:
    content = content.replace(target_s1, replace_s1, 1)
    print("Added specification table to Sheet 1!")
else:
    print("target_s1 not found directly, checking variations...")

p.write_text(content, encoding="utf-8")
print("Done editing spds_full_set.py")
