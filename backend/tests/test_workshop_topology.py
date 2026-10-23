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


def test_validator_reports_grid_match_as_unreviewed_hypothesis():
    validator = StructuralTopologyValidator()
    topo = validator.topo

    # World position corresponding to Row Б, Axis 5
    u_target = topo.transverse_u_coords[4] # axis 5
    v_target = topo.v_row_b_m
    w_x, w_y, w_z = topo.to_world(u_target, v_target, -6.0)

    res = validator.classify_element_role("column", (w_x, w_y, w_z), (0.8, 0.6, 9.5))
    assert res["review_state"] == "unreviewed"
    assert res["candidate_role"] == "column"
    assert res["grid_hypothesis"]["row"] == "Б"
    assert res["grid_hypothesis"]["axis"] == 5
    assert res["grid_hypothesis"]["status"] == "unverified_candidate"
    assert "mark" not in res
    assert "type" not in res
    assert "section" not in res
    assert "tolerance_status" not in res


def test_validator_keeps_off_grid_column_as_unreviewed_candidate():
    validator = StructuralTopologyValidator()
    topo = validator.topo

    # Inside clear span between Row Б and В (e.g. V = -10.0m)
    u_target = topo.transverse_u_coords[4]
    v_middle = -10.0
    w_x, w_y, w_z = topo.to_world(u_target, v_middle, -6.0)

    res = validator.classify_element_role("column", (w_x, w_y, w_z), (0.5, 0.5, 3.0))
    assert res["candidate_role"] == "column"
    assert res["review_state"] == "unreviewed"
    assert res["grid_hypothesis"]["status"] == "outside_nominal_grid_search_window"


def test_validator_identifies_crane_girder():
    validator = StructuralTopologyValidator()
    topo = validator.topo

    # Along Row В at crane level Z_crane
    u_mid = (topo.transverse_u_coords[2] + topo.transverse_u_coords[3]) / 2.0
    v_row = topo.v_row_c_m
    w_x, w_y, w_z = topo.to_world(u_mid, v_row, topo.z_crane_bracket_scan_m)

    res = validator.classify_element_role("beam", (w_x, w_y, w_z), (6.0, 0.3, 0.9))
    assert res["candidate_role"] == "beam"
    assert res["review_state"] == "unreviewed"
    assert "elevation_mark" not in res
    assert "section" not in res
    assert "tolerance_status" not in res


def test_validator_never_reports_engineering_tolerance_without_project_limit():
    validator = StructuralTopologyValidator()
    topo = validator.topo

    u_target = topo.transverse_u_coords[0]
    v_target = topo.v_row_a_m
    w_x, w_y, w_z = topo.to_world(u_target, v_target, -6.0)

    # Exact agreement with an unverified nominal grid is not an engineering tolerance check.
    res_exact = validator.classify_element_role("column", (w_x, w_y, w_z), (0.6, 0.5, 9.0))
    assert res_exact["grid_hypothesis"]["delta_u_mm"] == 0
    assert res_exact["review_state"] == "unreviewed"
    assert "tolerance_status" not in res_exact

    # Marginal (delta = 20 mm)
    u_off = u_target + 0.020
    w_x_off, w_y_off, w_z_off = topo.to_world(u_off, v_target, -6.0)
    res_marg = validator.classify_element_role("column", (w_x_off, w_y_off, w_z_off), (0.6, 0.5, 9.0))
    assert res_marg["grid_hypothesis"]["delta_u_mm"] == 20
    assert res_marg["review_state"] == "unreviewed"

    # Exceeded (delta = 40 mm)
    u_bad = u_target + 0.040
    w_x_bad, w_y_bad, w_z_bad = topo.to_world(u_bad, v_target, -6.0)
    res_bad = validator.classify_element_role("column", (w_x_bad, w_y_bad, w_z_bad), (0.6, 0.5, 9.0))
    assert res_bad["grid_hypothesis"]["delta_u_mm"] == 40
    assert res_bad["review_state"] == "unreviewed"


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
    assert summary["status"] == "review_required"
    assert summary["columns"]["total"] == 2
    assert summary["columns"]["unassessed"] == 2
    assert len(regularized) == 2
    assert regularized[0]["class_name"] == "column"
    assert regularized[1]["class_name"] == "column"
    assert regularized[0]["dimensions"]["nominal_grid_hypothesis"]["review_state"] == "unreviewed"
    assert "mark" not in regularized[0]["dimensions"]["nominal_grid_hypothesis"]

