"""Engineering quality and deformation report generator compliant with GOST R 58973-2020.

Produces official executive survey reports (Исполнительная геодезическая документация):
- General Project & Scanning Passport.
- Multi-station Registration Error Matrix (RMSE, target discrepancies).
- Structural Verticality & Deformation Schedule (СП 70.13330 compliance).
- Statistical summary of deviations.
"""
from __future__ import annotations

import datetime
import math
from pathlib import Path
from typing import Any, Mapping
import numpy as np


def generate_registration_passport(
    project_name: str,
    project_id: str,
    stations: list[dict[str, Any]],
    registration_results: dict[str, Any],
    instrument_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a registration report without inferring accuracy from fit residuals."""
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%d.%m.%Y %H:%M UTC")

    inst = {
        "scanner_model": None,
        "serial_number": None,
        "angular_accuracy_sec": None,
        "ranging_accuracy_mm": None,
        "calibration_date": None,
        **(instrument_info or {}),
    }

    def optional_finite_number(value: Any) -> float | None:
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    n_stations = len(stations)
    total_pts = sum(s.get("point_count", 0) for s in stations)
    fit_rmse_mm = optional_finite_number(registration_results.get("final_rmse_mm"))
    max_fit_error_mm = optional_finite_number(registration_results.get("max_error_mm"))

    # Pairwise station error matrix
    matrix_rows = []
    for i, st_a in enumerate(stations):
        row = {"station_id": st_a.get("id", f"ST_{i+1:02d}"), "errors_mm": []}
        for j, _st_b in enumerate(stations):
            # No pairwise residual is available in the registration contract.
            # A fit RMSE cannot be projected into invented station-to-station errors.
            row["errors_mm"].append(0.0 if i == j else None)
        matrix_rows.append(row)

    return {
        "report_title": "Паспорт лазерного сканирования и сшивки станций",
        "standard_references": ["ГОСТ Р 58973-2020", "СП 317.1325800.2017"],
        "generated_at": now_str,
        "project": {
            "name": project_name,
            "id": project_id,
        },
        "instrument": inst,
        "summary": {
            "total_stations": n_stations,
            "total_points": total_pts,
            "fit_rmse_mm": fit_rmse_mm,
            "max_fit_error_mm": max_fit_error_mm,
            "accuracy_status": "not_measured",
            "registration_status": "НЕ ИЗМЕРЕНО ПО НЕЗАВИСИМЫМ КОНТРОЛЬНЫМ ТОЧКАМ",
        },
        "pairwise_error_matrix": matrix_rows,
    }


def generate_deformation_bulletin_pdf(
    project_name: str,
    inspections: list[dict[str, Any]],
    output_pdf_path: str | Path,
) -> Path:
    """Render comprehensive executive structural verticality bulletin to PDF via matplotlib."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    out_file = Path(output_pdf_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    with PdfPages(out_file) as pdf:
        # Page 1: Title and Executive Summary
        fig = plt.figure(figsize=(11.69, 8.27), dpi=150)  # A4 Landscape
        fig.patch.set_facecolor("#FFFFFF")

        plt.text(0.05, 0.92, "ВЕДОМОСТЬ ОТКЛОНЕНИЙ И КРЕНОВ КОЛОНН (СП 70.13330.2012)", fontsize=14, fontweight="bold", color="#111827")
        plt.text(0.05, 0.87, f"Объект: {project_name} | Дата контроля: {datetime.date.today().strftime('%d.%m.%Y')}", fontsize=10, color="#4B5563")

        # Table data
        col_labels = ["Колонна", "H, м", "Крен ΔX, мм", "Крен ΔY, мм", "Полный крен, мм", "Допуск СП, мм", "Запас, мм", "Статус"]
        table_rows = []
        for insp in inspections:
            status_text = "НОРМА" if insp.get("status") == "compliant" else "ПРЕВЫШЕН"
            table_rows.append([
                insp.get("column_id", "—"),
                f"{insp.get('nominal_height_m', 0.0):.2f}",
                f"{insp.get('top_deviation_dx_mm', 0.0):+.1f}",
                f"{insp.get('top_deviation_dy_mm', 0.0):+.1f}",
                f"{insp.get('top_deviation_total_mm', 0.0):.1f}",
                f"{insp.get('limit_deviation_mm', 0.0):.1f}",
                f"{insp.get('margin_mm', 0.0):+.1f}",
                status_text,
            ])

        # Plot Table
        ax_table = fig.add_axes([0.05, 0.25, 0.90, 0.55])
        ax_table.axis("off")
        the_table = ax_table.table(
            cellText=table_rows,
            colLabels=col_labels,
            loc="center",
            cellLoc="center",
        )
        the_table.auto_set_font_size(False)
        the_table.set_fontsize(9)
        the_table.scale(1, 1.6)

        # Style headers
        for (row_idx, col_idx), cell in the_table.get_celld().items():
            if row_idx == 0:
                cell.set_facecolor("#171D24")
                cell.set_text_props(color="#FFFFFF", weight="bold")
            else:
                status_val = table_rows[row_idx - 1][7]
                if status_val == "ПРЕВЫШЕН":
                    cell.set_facecolor("#FEE2E2")
                elif row_idx % 2 == 0:
                    cell.set_facecolor("#F9FAFB")

        # Summary footer
        total_cols = len(inspections)
        compliant_cols = sum(1 for i in inspections if i.get("status") == "compliant")
        exceeded_cols = total_cols - compliant_cols

        footer_text = (
            f"Всего проинспектировано: {total_cols} конструкций | В допуске: {compliant_cols} | Превышений: {exceeded_cols}\n"
            f"Контроль выполнен в соответствии с требованиями СП 70.13330.2012 (Таблицы 4.9, 5.12). Инженер: SCAN AI Studio."
        )
        plt.text(0.05, 0.10, footer_text, fontsize=9, color="#1F2937", bbox=dict(boxstyle="round,pad=0.5", facecolor="#F3F4F6", edgecolor="#D1D5DB"))

        pdf.savefig(fig)
        plt.close(fig)

    return out_file
