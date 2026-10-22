import pytest
from scan2bim.structure.workshop_topology import WorkshopGridTopology, StructuralTopologyValidator


def test_workshop_grid_topology_spans_and_bays():
    topo = WorkshopGridTopology()

    assert topo.total_transverse_axes == 24
    assert len(topo.transverse_u_coords) == 24
    assert topo.bay_step_m == 6.0

    # Bay step along U
    u_coords = topo.transverse_u_coords
    for i in range(1, len(u_coords)):
        assert pytest.approx(u_coords[i] - u_coords[i - 1], 1e-3) == 6.0

    # 4 rows across 3 spans
    rows = topo.row_v_coords
    assert len(rows) == 4
    assert list(rows.keys()) == ["А", "Б", "В", "Г"]
    assert pytest.approx(rows["Б"] - rows["А"], 0.1) == 13.25
    assert pytest.approx(rows["В"] - rows["Б"], 0.1) == 11.70
    assert pytest.approx(rows["Г"] - rows["В"], 0.1) == 13.25


def test_validator_identifies_true_column_on_grid():
    validator = StructuralTopologyValidator()
    topo = validator.topo

    # World position corresponding to Row Б, Axis 5
    u_target = topo.transverse_u_coords[4] # axis 5
    v_target = topo.v_row_b_m
    w_x, w_y, w_z = topo.to_world(u_target, v_target, -6.0)

    res = validator.classify_element_role("column", (w_x, w_y, w_z), (0.8, 0.6, 9.5))
    assert res["is_structural"] is True
    assert res["structural_role"] == "column"
    assert res["mark"] == "К-Б5"
    assert res["row"] == "Б"
    assert res["axis"] == 5
    assert res["type"] == "К-2"


def test_validator_rejects_column_inside_clear_span():
    validator = StructuralTopologyValidator()
    topo = validator.topo

    # Inside clear span between Row Б and В (e.g. V = -10.0m)
    u_target = topo.transverse_u_coords[4]
    v_middle = -10.0
    w_x, w_y, w_z = topo.to_world(u_target, v_middle, -6.0)

    res = validator.classify_element_role("column", (w_x, w_y, w_z), (0.5, 0.5, 3.0))
    assert res["is_structural"] is False
    assert res["structural_role"] == "equipment_or_clutter"


def test_validator_identifies_crane_girder():
    validator = StructuralTopologyValidator()
    topo = validator.topo

    # Along Row В at crane level Z_crane
    u_mid = (topo.transverse_u_coords[2] + topo.transverse_u_coords[3]) / 2.0
    v_row = topo.v_row_c_m
    w_x, w_y, w_z = topo.to_world(u_mid, v_row, topo.z_crane_bracket_scan_m)

    res = validator.classify_element_role("beam", (w_x, w_y, w_z), (6.0, 0.3, 0.9))
    assert res["is_structural"] is True
    assert res["structural_role"] == "crane_girder"
    assert res["elevation_mark"] == "+6.800"
