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
    assert res["mark"] == "БП-В3-4"
    assert res["tolerance_status"] == "compliant"


def test_validator_tolerance_evaluation():
    validator = StructuralTopologyValidator()
    topo = validator.topo

    u_target = topo.transverse_u_coords[0]
    v_target = topo.v_row_a_m
    w_x, w_y, w_z = topo.to_world(u_target, v_target, -6.0)

    # Compliant (exact match, delta = 0)
    res_exact = validator.classify_element_role("column", (w_x, w_y, w_z), (0.6, 0.5, 9.0))
    assert res_exact["delta_r_mm"] == 0
    assert res_exact["tolerance_status"] == "compliant"
    assert "В допуске СП 70" in res_exact["tolerance_badge"]

    # Marginal (delta = 20 mm)
    u_off = u_target + 0.020
    w_x_off, w_y_off, w_z_off = topo.to_world(u_off, v_target, -6.0)
    res_marg = validator.classify_element_role("column", (w_x_off, w_y_off, w_z_off), (0.6, 0.5, 9.0))
    assert res_marg["tolerance_status"] == "marginal"

    # Exceeded (delta = 40 mm)
    u_bad = u_target + 0.040
    w_x_bad, w_y_bad, w_z_bad = topo.to_world(u_bad, v_target, -6.0)
    res_bad = validator.classify_element_role("column", (w_x_bad, w_y_bad, w_z_bad), (0.6, 0.5, 9.0))
    assert res_bad["tolerance_status"] == "exceeded"


def test_regularize_workshop_model_full():
    from scan2bim.structure.workshop_topology import regularize_workshop_model

    topo = WorkshopGridTopology()
    w_x, w_y, w_z = topo.to_world(topo.transverse_u_coords[0], topo.v_row_a_m, -6.0)
    
    mock_elements = [
        {
            "id": "col1",
            "class_name": "column",
            "geometry": {"center": [w_x, w_y, w_z], "sizes": {"length": 0.6, "thickness": 0.5, "height": 9.0}},
            "dimensions": {},
        },
        {
            "id": "col_clutter",
            "class_name": "column",
            "geometry": {"center": [w_x, w_y + 6.0, w_z], "sizes": {"length": 0.6, "thickness": 0.5, "height": 3.0}},
            "dimensions": {},
        },
    ]

    regularized, summary = regularize_workshop_model(mock_elements)
    assert summary["status"] == "success"
    assert summary["columns"]["total"] == 1
    assert summary["columns"]["compliant"] == 1
    assert regularized[0]["dimensions"]["mark"] == "К-А1"
    # Clutter column was rejected and marked unknown
    assert len(regularized) == 1

