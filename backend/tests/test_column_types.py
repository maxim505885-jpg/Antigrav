import math

from scan2bim.structure.column_types import column_descriptor, propose_column_types


def _column(
    *,
    length=0.42,
    thickness=0.30,
    angle=0.0,
    dimensions=None,
    measured=True,
    inferred=False,
    class_name="column",
):
    return {
        "id": "column-1",
        "class_name": class_name,
        "measured": measured,
        "inferred": inferred,
        "geometry": {
            "kind": "oriented_box",
            "center": [10.0, 20.0, 5.0],
            "sizes": {"length": length, "thickness": thickness, "height": 6.0},
            "rotation_z": angle,
        },
        "dimensions": dimensions or {},
    }


def test_descriptor_uses_measured_sides_and_normalizes_the_long_axis():
    result = column_descriptor(_column(angle=math.pi / 2))

    assert result["eligible"] is True
    assert result["element_id"] == "column-1"
    assert result["long_side_m"] == 0.42
    assert result["short_side_m"] == 0.30
    assert result["area_m2"] == 0.126
    assert math.isclose(result["long_axis_angle_rad"], math.pi / 2)
    assert result["measurement_sources"] == {
        "long_side_m": "geometry.sizes.length",
        "short_side_m": "geometry.sizes.thickness",
        "rotation_z": "geometry.rotation_z",
    }


def test_descriptor_handles_swapped_side_fields_without_changing_the_section():
    result = column_descriptor(_column(length=0.30, thickness=0.42))

    assert result["long_side_m"] == 0.42
    assert result["short_side_m"] == 0.30
    assert math.isclose(result["long_axis_angle_rad"], math.pi / 2)


def test_descriptor_falls_back_to_measured_dimensions_when_box_sizes_are_missing():
    element = _column()
    element["geometry"]["sizes"] = {"height": 6.0}
    element["dimensions"].update({"length_m": 0.42, "thickness_m": 0.30})

    result = column_descriptor(element)

    assert result["eligible"] is True
    assert result["long_side_m"] == 0.42
    assert result["short_side_m"] == 0.30
    assert result["measurement_sources"]["long_side_m"] == "dimensions.length_m"
    assert result["measurement_sources"]["short_side_m"] == "dimensions.thickness_m"


def test_descriptor_marks_missing_or_nonpositive_sides_ineligible():
    missing = _column()
    missing["geometry"]["sizes"].pop("thickness")
    nonpositive = _column(thickness=0.0)

    assert column_descriptor(missing)["eligible"] is False
    assert "missing_short_side" in column_descriptor(missing)["reasons"]
    assert column_descriptor(nonpositive)["eligible"] is False
    assert "invalid_short_side" in column_descriptor(nonpositive)["reasons"]


def test_descriptor_rejects_unmeasured_inferred_and_noncolumn_candidates():
    unmeasured = _column(measured=False)
    inferred = _column(inferred=True)
    beam = _column(class_name="beam")

    assert "not_measured" in column_descriptor(unmeasured)["reasons"]
    assert "inferred_geometry" in column_descriptor(inferred)["reasons"]
    assert "not_a_column" in column_descriptor(beam)["reasons"]


def test_descriptor_and_grouping_exclude_rejected_and_invalidated_elements():
    rejected = _column()
    rejected.update({"id": "rejected", "review_status": "rejected"})
    invalidated = _column()
    invalidated.update({
        "id": "invalidated",
        "source": "invalidated_synthetic_ground_truth",
        "review_status": "invalidated",
    })

    rejected_result = column_descriptor(rejected)
    invalidated_result = column_descriptor(invalidated)

    assert rejected_result["eligible"] is False
    assert "element_rejected" in rejected_result["reasons"]
    assert invalidated_result["eligible"] is False
    assert "invalidated_source" in invalidated_result["reasons"]
    assert propose_column_types([rejected, invalidated], linear_tolerance_m=0.01) == []


def test_descriptor_preserves_stepped_and_built_up_section_evidence():
    stepped = _column(dimensions={
        "column_type": "stepped",
        "section_coverage": 0.5,
        "section_profile": [{"z": 1.0, "area_m2": 0.42}, {"z": 5.0, "area_m2": 0.24}],
        "base_area_m2": 0.42,
        "top_area_m2": 0.24,
    })
    built_up = _column(dimensions={"column_type": "built_up", "section_fill": 0.38})

    stepped_result = column_descriptor(stepped)
    built_up_result = column_descriptor(built_up)

    assert stepped_result["morphology"] == "stepped"
    assert stepped_result["evidence_coverage"] == 0.5
    assert stepped_result["morphology_evidence"]["section_profile"] == stepped["dimensions"]["section_profile"]
    assert built_up_result["morphology"] == "built_up"
    assert built_up_result["morphology_evidence"]["section_fill"] == 0.38


def test_descriptor_does_not_invent_an_orientation_when_rotation_is_missing():
    element = _column()
    element["geometry"].pop("rotation_z")

    result = column_descriptor(element)

    assert result["eligible"] is True
    assert result["long_axis_angle_rad"] is None
    assert result["measurement_sources"]["rotation_z"] is None


def test_descriptor_normalizes_each_right_angle_rotation_of_the_long_side():
    for rotation, expected in (
        (0.0, 0.0),
        (math.pi / 2, math.pi / 2),
        (math.pi, 0.0),
        (3 * math.pi / 2, math.pi / 2),
    ):
        result = column_descriptor(_column(angle=rotation))
        assert math.isclose(result["long_axis_angle_rad"], expected)


def test_descriptor_requires_an_element_id_for_type_membership():
    element = _column()
    element.pop("id")

    result = column_descriptor(element)

    assert result["eligible"] is False
    assert "missing_element_id" in result["reasons"]


def test_descriptor_excludes_columns_with_only_partial_or_coarse_section_evidence():
    partial = _column()
    partial["dimensions"].update({
        "section_status": "partial_one_axis",
        "measured_section_axes_m": {"length": None, "thickness": 0.30},
    })
    coarse = _column()
    coarse["dimensions"]["section_status"] = "coarse_grid_only"

    partial_result = column_descriptor(partial)
    coarse_result = column_descriptor(coarse)

    assert partial_result["eligible"] is False
    assert "incomplete_section_measurement" in partial_result["reasons"]
    assert coarse_result["eligible"] is False
    assert "incomplete_section_measurement" in coarse_result["reasons"]


def test_descriptor_prefers_point_measured_dimensions_over_coarse_box_sizes():
    element = _column(length=0.50, thickness=0.40)
    element["dimensions"].update({
        "section_status": "measured_4_sides",
        "measured_section_m": [0.42, 0.30],
    })

    result = column_descriptor(element)

    assert result["eligible"] is True
    assert result["long_side_m"] == 0.42
    assert result["short_side_m"] == 0.30
    assert result["measurement_sources"] == {
        "long_side_m": "dimensions.measured_section_m[0]",
        "short_side_m": "dimensions.measured_section_m[1]",
        "rotation_z": "geometry.rotation_z",
    }


def test_repeated_measured_sections_form_a_deterministic_proposal():
    elements = [_column(), _column(length=0.421, thickness=0.301)]
    elements[0]["id"] = "column-b"
    elements[1]["id"] = "column-a"

    proposal = propose_column_types(elements, linear_tolerance_m=0.005)

    assert len(proposal) == 1
    assert proposal[0]["status"] == "proposed"
    assert proposal[0]["member_element_ids"] == ["column-a", "column-b"]
    assert proposal[0]["representative_sides_m"] == {
        "long": 0.4205,
        "short": 0.3005,
    }
    assert proposal[0]["morphology_agreement"] is True
    assert set(proposal[0]["residuals_m"]) == {"column-a", "column-b"}


def test_singletons_remain_individual_proposals_and_close_distinct_sizes_split():
    first = _column(length=0.4, thickness=0.3)
    second = _column(length=0.6, thickness=0.4)
    first["id"], second["id"] = "column-1", "column-2"

    proposals = propose_column_types([first, second], linear_tolerance_m=0.001)

    assert [proposal["member_element_ids"] for proposal in proposals] == [
        ["column-1"],
        ["column-2"],
    ]


def test_both_absolute_and_relative_tolerances_bound_dimension_noise():
    base = _column(length=0.5, thickness=0.4)
    near = _column(length=0.504, thickness=0.403)
    far = _column(length=0.51, thickness=0.4)
    base["id"], near["id"], far["id"] = "a", "b", "c"

    proposals = propose_column_types(
        [base, near, far], linear_tolerance_m=0.001, relative_tolerance=0.01
    )

    assert [proposal["member_element_ids"] for proposal in proposals] == [["a", "b"], ["c"]]


def test_linear_tolerance_boundary_is_inclusive_without_snapping_measurements():
    base = _column(length=0.5, thickness=0.4)
    boundary = _column(length=0.505, thickness=0.4)
    outside = _column(length=0.5051, thickness=0.4)
    base["id"], boundary["id"], outside["id"] = "a", "b", "c"

    proposals = propose_column_types(
        [base, boundary, outside], linear_tolerance_m=0.005, relative_tolerance=0
    )

    assert [proposal["member_element_ids"] for proposal in proposals] == [["a", "b"], ["c"]]
    assert base["geometry"]["sizes"]["length"] == 0.5
    assert boundary["geometry"]["sizes"]["length"] == 0.505


def test_rectangles_with_right_angle_orientation_changes_group_without_snapping():
    zero = _column(length=0.5, thickness=0.3, angle=0.0)
    ninety = _column(length=0.5, thickness=0.3, angle=math.pi / 2)
    zero["id"], ninety["id"] = "a", "b"

    proposals = propose_column_types([zero, ninety], linear_tolerance_m=0.001)

    assert len(proposals) == 1
    assert column_descriptor(zero)["long_axis_angle_rad"] == 0.0
    assert math.isclose(column_descriptor(ninety)["long_axis_angle_rad"], math.pi / 2)


def test_stepped_and_solid_morphologies_do_not_merge():
    stepped = _column(dimensions={"column_type": "stepped"})
    solid = _column(dimensions={"column_type": "solid"})
    stepped["id"], solid["id"] = "a", "b"

    proposals = propose_column_types([stepped, solid], linear_tolerance_m=0.001)

    assert len(proposals) == 2
    assert {proposal["morphology"] for proposal in proposals} == {"stepped", "solid"}


def test_grouping_is_stable_when_input_order_changes():
    elements = []
    for element_id, length in (("c", 0.42), ("a", 0.421), ("b", 0.60)):
        element = _column(length=length)
        element["id"] = element_id
        elements.append(element)

    first = propose_column_types(elements, linear_tolerance_m=0.005)
    second = propose_column_types(list(reversed(elements)), linear_tolerance_m=0.005)

    assert first == second
