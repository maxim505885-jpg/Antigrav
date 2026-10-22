import sys
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))

import json
import math
import ezdxf
from scan2bim.cad.spds import (
    setup_spds_layers_and_styles,
    draw_spds_sheet_frame,
    draw_spds_title_block,
    draw_spds_axis_bubble,
    draw_spds_dimension_chain,
    draw_spds_level_mark,
)
from scan2bim.cad.spds_tables import draw_spds_specification_table

# Load confirmed grid columns
data_path = Path("data/output/workshop_release/clean_grid_columns.json")
data = json.loads(data_path.read_text(encoding="utf-8"))

x_bays = data["x_bays"]       # 23 axes: 1 .. 23 (step 6.000m, total 132m)
y_spans = data["y_spans"]     # 4 rows: А, Б, В, Г (spans 12.7m, 12.3m, 13.0m)
columns = data["columns"]     # 84 real columns

# Shift origin so coordinates start comfortably at (0, 0)
x_min, x_max = min(x_bays), max(x_bays)
y_min, y_max = min(y_spans), max(y_spans)

shift_x = -x_min + 15.0
shift_y = -y_min + 15.0

x_bays_shifted = [x + shift_x for x in x_bays]
y_spans_shifted = [y + shift_y for y in y_spans]

out_dir = Path("data/output/workshop_release/clean_drawings")
out_dir.mkdir(parents=True, exist_ok=True)

# -------------------------------------------------------------
# Лист 1: План расположения колонн цеха на отм. 0.000 (ГОСТ 21.501)
# -------------------------------------------------------------
scale = 200.0 # Масштаб 1:200
doc1 = ezdxf.new("R2000")
setup_spds_layers_and_styles(doc1)
msp1 = doc1.modelspace()

# Frame A1 (841 x 594 mm -> 168.2 x 118.8 m at 1:200)
frame_box = draw_spds_sheet_frame(msp1, origin_x=0.0, origin_y=0.0, format_name="A1", scale_factor=scale)
inner_x0, inner_y0, inner_x1, inner_y1 = frame_box

# Title block (Форма 3 ГОСТ 21.101-2020)
draw_spds_title_block(
    msp1,
    bottom_right_x=inner_x1,
    bottom_right_y=inner_y0,
    project_title="Производственный корпус цеха 1.rcs",
    sheet_title="Схема расположения колонн цеха на отм. 0.000",
    scale_factor=scale,
    stage="Р",
    sheet_num=1,
    total_sheets=5,
)

# Specification table (Форма 7 ГОСТ 21.501-2018)
count_k1 = sum(1 for c in columns if c["type"] == "К-1")
count_k2 = sum(1 for c in columns if c["type"] == "К-2")

spec_items = [
    {"pos": "К-1", "designation": "Серия 1.424.1-5", "name": "Колонна К-1 крайнего ряда (двутавр 600х500)", "count": count_k1, "mass": 1850, "comment": ""},
    {"pos": "К-2", "designation": "Серия 1.424.1-5", "name": "Колонна К-2 среднего ряда ступенчатая (800х600)", "count": count_k2, "mass": 2420, "comment": ""},
]
draw_spds_specification_table(
    msp1,
    top_right_x=inner_x1,
    top_right_y=inner_y0 + (55.0 + len(spec_items) * 8.0 + 20.0) * (scale / 1000.0),
    items=spec_items,
    scale_factor=scale,
    title="Спецификация к схеме расположения колонн",
)

# Draw Grid Axes
bubble_r = 0.005 * scale # 1.0m bubble

# Vertical axes 1..23
for idx, x_val in enumerate(x_bays_shifted, start=1):
    y_start = min(y_spans_shifted) - 6.0
    y_end = max(y_spans_shifted) + 6.0
    msp1.add_line((x_val, y_start, 0), (x_val, y_end, 0), dxfattribs={"layer": "SPDS-AXES"})
    draw_spds_axis_bubble(msp1, x_val, y_start - bubble_r * 1.5, str(idx), radius=bubble_r)

# Horizontal axes А, Б, В, Г
cyr_rows = ["А", "Б", "В", "Г"]
for idx, y_val in enumerate(y_spans_shifted):
    x_start = min(x_bays_shifted) - 6.0
    x_end = max(x_bays_shifted) + 6.0
    msp1.add_line((x_start, y_val, 0), (x_end, y_val, 0), dxfattribs={"layer": "SPDS-AXES"})
    draw_spds_axis_bubble(msp1, x_start - bubble_r * 1.5, y_val, cyr_rows[idx], radius=bubble_r)

# Dimension chains 6000 mm
draw_spds_dimension_chain(msp1, x_bays_shifted, fixed_coord=min(y_spans_shifted) - 6.0, axis="x", offset=-bubble_r * 4.0, tick_size=bubble_r * 0.5)
draw_spds_dimension_chain(msp1, y_spans_shifted, fixed_coord=min(x_bays_shifted) - 6.0, axis="y", offset=-bubble_r * 4.0, tick_size=bubble_r * 0.5)

# Draw Columns EXACTLY ON GRID ROWS
for col in columns:
    gx = col["x_grid"] + shift_x
    gy = col["y_grid"] + shift_y
    l = col["dimensions"]["length_m"]
    t = col["dimensions"]["thickness_m"]
    
    # Column rectangle centered on grid node
    corners = [
        (gx - l/2, gy - t/2),
        (gx + l/2, gy - t/2),
        (gx + l/2, gy + t/2),
        (gx - l/2, gy + t/2),
    ]
    msp1.add_lwpolyline(corners, close=True, dxfattribs={"layer": "SPDS-COLUMNS"})
    
    # Mark label
    mark = col["type"]
    text = msp1.add_text(mark, dxfattribs={"layer": "SPDS-COLUMNS", "height": 0.0022 * scale})
    text.dxf.halign = 1 # Center
    text.dxf.align_point = (gx, gy + t/2 + 0.4, 0.0)

# Stamp technical note
notes = [
    "1. Колонны каркаса запроектированы по серии 1.424.1-5 вып. 1.",
    "2. Сетка координационных осей принята по натурным обмерам лазерного сканирования 1.rcs.",
    "3. Отметка чистого пола 0.000 соответствует абсолютной отметке согласно генплану.",
    "4. Размеры между осями даны в миллиметрах (шаг колонн 6000 мм).",
]
ty = inner_y0 + 15.0
for note in notes:
    msp1.add_text(note, dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": 0.0025 * scale}).set_placement((inner_x0 + 10.0, ty))
    ty -= 0.004 * scale

dxf_1 = out_dir / "01_plan_kolonn_SPDS.dxf"
doc1.saveas(str(dxf_1))
print(f"Created clean sheet 1 DXF: {dxf_1.name} ({dxf_1.stat().st_size / 1024:.1f} KB)")
