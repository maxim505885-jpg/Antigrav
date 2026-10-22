from pathlib import Path

p = Path("backend/scan2bim/cad/spds_full_set.py")
lines = p.read_text(encoding="utf-8").splitlines()

# Find the draw_spds_title_block in sheet 1
for i, line in enumerate(lines):
    if "total_sheets=4," in line and i > 600 and i < 640:
        lines[i] = "        total_sheets=5,"
        # Insert table code right after this title block call
        table_code = """
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
        lines[i+1] = lines[i+1] + table_code
        print("Updated Sheet 1 with specification table!")
        break

# Also update Sheet 2 crane girders title block
for i, line in enumerate(lines):
    if "sheet_num=2," in line:
        for j in range(i, i+10):
            if "total_sheets=4," in lines[j]:
                lines[j] = "        total_sheets=5,"
                table_code_2 = """
    # Таблица спецификации подкрановых конструкций по ГОСТ 21.501-2018
    spec_items_2 = [
        {"pos": "БП-1", "designation": "Серия 1.426.2-7", "name": "Балка подкрановая Б-6 (L=6м)", "count": 48, "mass": 1250, "comment": ""},
        {"pos": "Р-1", "designation": "ГОСТ 7173-54", "name": "Рельс крановый КР-70", "count": "272 м", "mass": "19.3 т", "comment": "L=136м х 2"},
        {"pos": "УП-1", "designation": "Серия 1.426.2-7", "name": "Упор концевой тупиковый", "count": 4, "mass": 85, "comment": ""},
    ]
    draw_spds_specification_table(
        msp,
        top_right_x=inner_box[2],
        top_right_y=inner_box[1] + (55.0 + len(spec_items_2) * 8.0 + 20.0) * (scale_factor / 1000.0),
        items=spec_items_2,
        scale_factor=scale_factor,
        title="Спецификация к схеме подкрановых путей",
    )"""
                lines[j+1] = lines[j+1] + table_code_2
                print("Updated Sheet 2 with crane specification table!")
                break
        break

p.write_text("\n".join(lines), encoding="utf-8")
print("Done inserting SPDS tables!")
