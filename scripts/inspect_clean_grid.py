import json

with open('data/output/workshop_release/clean_grid_columns.json', encoding='utf-8') as f:
    data = json.load(f)

print(f"Total columns in clean_grid: {len(data['columns'])}")
print(f"Bays: {data['x_bays']}")
print(f"Spans: {data['y_spans']}")
print(f"Rows: {data['rows']}")

for c in data['columns'][:15]:
    print(f"{c['mark']:6s} row={c['row']} bay={c['bay']:2d} grid=({c['x_grid']:6.1f}, {c['y_grid']:6.1f}) actual=({c['x_actual']:7.2f}, {c['y_actual']:7.2f}) pt_count={c.get('point_count')}")
