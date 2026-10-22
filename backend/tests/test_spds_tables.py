import pytest
import ezdxf
from scan2bim.cad.spds_tables import draw_spds_specification_table
from scan2bim.cad.spds import setup_spds_layers_and_styles

def test_draw_spds_specification_table():
    doc = ezdxf.new(dxfversion="R2010")
    setup_spds_layers_and_styles(doc)
    msp = doc.modelspace()

    items = [
        {"pos": "К-1", "designation": "Серия 1.424.1-5", "name": "Колонна К-1 (двутавр)", "count": 140, "mass": 1850, "comment": ""},
        {"pos": "К-2", "designation": "Серия 1.424.1-5", "name": "Колонна К-2 торцевая", "count": 93, "mass": 1420, "comment": ""},
    ]

    bottom_y = draw_spds_specification_table(msp, top_right_x=100.0, top_right_y=50.0, items=items, scale_factor=200.0)
    assert bottom_y < 50.0

    # Проверяем наличие добавленных примитивов таблицы в modelspace
    texts = [e.dxf.text for e in msp.query("TEXT")]
    assert "Спецификация к схеме расположения элементов" in texts
    assert "Колонна К-1 (двутавр)" in texts
    assert "Серия 1.424.1-5" in texts
