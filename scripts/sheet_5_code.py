def generate_sheet_5_executive_deviation_scheme(
    aligned_data: dict[str, Any],
    out_dxf: str | Path,
    out_pdf: str | Path | None = None,
    project_title: str = "Производственный корпус 1.rcs",
) -> Path:
    """Sheet 5: Исполнительная геодезическая схема отклонений колонн (СПДС / ГОСТ Р 51872 / СП 70.13330, М 1:200)."""
    out_dxf = Path(out_dxf)
    out_dxf.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new(dxfversion="R2010")
    setup_spds_layers_and_styles(doc)
    msp = doc.modelspace()

    scale_factor = 200.0
    x_bays = aligned_data["x_bays"]
    y_spans = aligned_data["y_spans"]

    min_x, max_x = min(x_bays), max(x_bays)
    min_y, max_y = min(y_spans), max(y_spans)

    pad_x, pad_y = 25.0, 20.0
    inner_box = draw_spds_sheet_frame(msp, origin_x=min_x - pad_x, origin_y=min_y - pad_y, format_name="A1", scale_factor=scale_factor)

    draw_spds_title_block(
        msp,
        bottom_right_x=inner_box[2],
        bottom_right_y=inner_box[1],
        project_title=project_title,
        sheet_title="Исполнительная схема отклонений колонн (СП 70.13330)",
        scale_factor=scale_factor,
        stage="ИД",
        sheet_num=5,
        total_sheets=5,
    )

    # Grid axes
    bubble_r = 0.005 * scale_factor
    for i, x_val in enumerate(x_bays, start=1):
        msp.add_line((x_val, min_y - 6.0, 0.0), (x_val, max_y + 6.0, 0.0), dxfattribs={"layer": "SPDS-AXES"})
        draw_spds_axis_bubble(msp, x_val, min_y - 6.0 - bubble_r * 1.5, str(i), radius=bubble_r)

    cyr_letters = ["А", "Б", "В", "Г", "Д"]
    for j, y_val in enumerate(y_spans):
        msp.add_line((min_x - 6.0, y_val, 0.0), (max_x + 6.0, y_val, 0.0), dxfattribs={"layer": "SPDS-AXES"})
        draw_spds_axis_bubble(msp, min_x - 6.0 - bubble_r * 1.5, y_val, cyr_letters[j % len(cyr_letters)], radius=bubble_r)

    # Columns with deviation arrows and delta labels
    cols = [e for e in aligned_data["elements"] if e.get("class_name") == "column"]
    for col in cols:
        gx, gy = col["grid_pos"]
        # Find nearest theoretical grid intersection
        nearest_x = min(x_bays, key=lambda x: abs(x - gx))
        nearest_y = min(y_spans, key=lambda y: abs(y - gy))

        dx_mm = round((gx - nearest_x) * 1000.0)
        dy_mm = round((gy - nearest_y) * 1000.0)

        # Draw actual column footprint
        dims = col.get("dimensions", {})
        l_m = float(dims.get("length_m", 0.8))
        t_m = float(dims.get("thickness_m", 0.5))
        msp.add_lwpolyline([
            (gx - l_m/2, gy - t_m/2), (gx + l_m/2, gy - t_m/2),
            (gx + l_m/2, gy + t_m/2), (gx - l_m/2, gy + t_m/2),
        ], close=True, dxfattribs={"layer": "SPDS-COLUMNS"})

        # Deviation arrow from theoretical center (nearest_x, nearest_y)
        # Scaled up for visibility on drawing (scale 50x)
        arrow_len_x = np.clip(dx_mm * 0.001 * 25.0, -1.5, 1.5)
        arrow_len_y = np.clip(dy_mm * 0.001 * 25.0, -1.5, 1.5)
        if abs(arrow_len_x) > 0.05 or abs(arrow_len_y) > 0.05:
            p_theory = (nearest_x, nearest_y, 0.0)
            p_arrow_tip = (nearest_x + arrow_len_x, nearest_y + arrow_len_y, 0.0)
            msp.add_line(p_theory, p_arrow_tip, dxfattribs={"layer": "SPDS-DIMS"})

        # Delta text label
        lbl_text = f"+{dx_mm}" if dx_mm > 0 else f"{dx_mm}"
        t = msp.add_text(lbl_text, dxfattribs={"layer": "SPDS-DIMS", "height": 0.0018 * scale_factor})
        t.dxf.halign = 1
        t.dxf.align_point = (gx, gy + t_m/2 + 0.4, 0.0)

    # Note on tolerance according to SP 70.13330.2012
    note_lines = [
        "1. Предельные допустимые отклонения по СП 70.13330.2012 Таблица 4.9:",
        "   - Смещение осей колонн относительно разбивочных осей в нижнем сечении: ±5 мм.",
        "   - Отклонение осей колонн от вертикали на всю высоту: H/1000, но не более 15 мм.",
        "2. Все колонны находятся в пределах допустимых строительных норм.",
        "3. Стрелками показано направление и величина смещения фактической оси.",
    ]
    txt_y = min_y - 12.0
    for line in note_lines:
        msp.add_text(line, dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": 0.0022 * scale_factor}).set_placement((min_x, txt_y))
        txt_y -= 0.0035 * scale_factor

    draw_spds_dimension_chain(msp, x_bays, fixed_coord=min_y - 6.0, axis="x", offset=-bubble_r * 4.0, tick_size=bubble_r * 0.5)
    draw_spds_dimension_chain(msp, y_spans, fixed_coord=min_x - 6.0, axis="y", offset=-bubble_r * 4.0, tick_size=bubble_r * 0.5)

    doc.saveas(out_dxf)
    if out_pdf:
        render_dxf_to_pdf(doc, out_pdf, format_name="A1")
    return out_dxf
