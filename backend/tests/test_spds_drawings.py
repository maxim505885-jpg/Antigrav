import ezdxf
import pytest
from scan2bim.cad.spds import (
    setup_spds_layers_and_styles,
    draw_spds_sheet_frame,
    draw_spds_title_block,
    draw_spds_axis_bubble,
    draw_spds_dimension_chain,
)


def test_spds_layers_and_sheet_frame_creation(tmp_path):
    doc = ezdxf.new()
    setup_spds_layers_and_styles(doc)
    msp = doc.modelspace()

    inner_box = draw_spds_sheet_frame(msp, origin_x=0, origin_y=0, format_name="A3", scale_factor=100.0)
    assert inner_box[0] > 0
    assert inner_box[1] > 0
    assert inner_box[2] > inner_box[0]
    assert inner_box[3] > inner_box[1]

    draw_spds_title_block(
        msp,
        bottom_right_x=inner_box[2],
        bottom_right_y=inner_box[1],
        project_title="Производственный цех 1.rcs",
        sheet_title="Схема расположения колонн и осей",
        scale_factor=100.0,
    )

    draw_spds_axis_bubble(msp, center_x=0.0, center_y=10.0, label="1", radius=0.5)
    draw_spds_dimension_chain(msp, [0.0, 6.0, 12.0, 18.0], fixed_coord=15.0, axis="x", offset=2.0)

    audit = doc.audit()
    assert len(audit.errors) == 0

    out_file = tmp_path / "spds_test.dxf"
    doc.saveas(out_file)
    assert out_file.exists()
    assert out_file.stat().st_size > 0
