"""Tests for executive deformation bulletins and GOST R 58973 registration passports."""
import pytest
from pathlib import Path
from scan2bim.reports.executive_reports import (
    generate_registration_passport,
    generate_deformation_bulletin_pdf,
)


def test_generate_registration_passport():
    stations = [
        {"id": "ST_01", "point_count": 1000000},
        {"id": "ST_02", "point_count": 1200000},
        {"id": "ST_03", "point_count": 950000},
    ]
    results = {"final_rmse_mm": 2.3, "max_error_mm": 3.8}

    passport = generate_registration_passport(
        project_name="Цех Проката",
        project_id="prj_001",
        stations=stations,
        registration_results=results,
    )

    assert passport["report_title"] == "Паспорт лазерного сканирования и сшивки станций"
    assert passport["summary"]["total_stations"] == 3
    assert passport["summary"]["total_points"] == 3150000
    assert passport["summary"]["mean_rmse_mm"] == 2.3
    assert "СООТВЕТСТВУЕТ" in passport["summary"]["registration_status"]
    assert len(passport["pairwise_error_matrix"]) == 3


def test_generate_deformation_bulletin_pdf(tmp_path):
    inspections = [
        {
            "column_id": "К-01",
            "nominal_height_m": 8.4,
            "top_deviation_dx_mm": 4.2,
            "top_deviation_dy_mm": -2.1,
            "top_deviation_total_mm": 4.7,
            "limit_deviation_mm": 8.4,
            "margin_mm": 3.7,
            "status": "compliant",
        },
        {
            "column_id": "К-02",
            "nominal_height_m": 8.4,
            "top_deviation_dx_mm": 11.5,
            "top_deviation_dy_mm": 6.0,
            "top_deviation_total_mm": 12.9,
            "limit_deviation_mm": 8.4,
            "margin_mm": -4.5,
            "status": "exceeded",
        },
    ]

    out_pdf = tmp_path / "deformation_bulletin.pdf"
    res_path = generate_deformation_bulletin_pdf("Цех Проката", inspections, out_pdf)

    assert res_path.exists()
    assert res_path.stat().st_size > 1000
