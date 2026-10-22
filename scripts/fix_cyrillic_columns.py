import json
from scan2bim.db import rows, execute

cols = rows("SELECT id, dimensions_json, metadata_json, geometry_json FROM elements WHERE cloud_id = 'workshop_cloud' AND class_name = 'column'")
print(f"Updating {len(cols)} columns to pure Cyrillic SPDS standard...")

# Map Latin row to Cyrillic row
row_map = {
    'A': 'А',
    'B': 'Б',
    'C': 'В',
    'D': 'Г',
    'А': 'А',
    'Б': 'Б',
    'В': 'В',
    'Г': 'Г',
}

for c in cols:
    elem_id = c['id']
    d = json.loads(c['dimensions_json'])
    m = json.loads(c['metadata_json'])
    g = json.loads(c['geometry_json'])
    
    raw_row = d.get('row', 'A')
    cyr_row = row_map.get(raw_row, 'А')
    axis = d.get('axis', 1)
    
    col_type = 'К-2' if cyr_row in ('Б', 'В') else 'К-1'
    mark = f"К-{cyr_row}{axis}"
    
    d['row'] = cyr_row
    d['mark'] = mark
    d['type'] = col_type
    d['column_type_label'] = col_type
    d['section_type'] = col_type
    d['structural_status'] = 'confirmed_grid_column'
    
    descr = f"Колонна {col_type} среднего ряда ступенчатая (800х600 мм)" if cyr_row in ('Б', 'В') else f"Колонна {col_type} крайнего ряда (600х500 мм)"
    m['row_axis'] = cyr_row
    m['mark'] = mark
    m['description'] = descr
    g['note'] = f"Несущая колонна {mark} каркаса цеха (шаг 6000 мм, ряд {cyr_row}, ось {axis})"
    
    execute(
        "UPDATE elements SET dimensions_json = ?, metadata_json = ?, geometry_json = ? WHERE id = ?",
        (json.dumps(d, ensure_ascii=False), json.dumps(m, ensure_ascii=False), json.dumps(g, ensure_ascii=False), elem_id)
    )

print("Columns successfully updated with Cyrillic SPDS marks!")
