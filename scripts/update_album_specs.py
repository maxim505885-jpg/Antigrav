p = "backend/scan2bim/cad/spds_full_set.py"
with open(p, "r", encoding="utf-8") as f:
    text = f.read()

target = """    sheet_specs = (
        ("sheet_1_columns", generate_sheet_1_columns_plan),
        ("sheet_2_crane", generate_sheet_2_crane_plan),
        ("sheet_3_section", generate_sheet_3_transverse_section),
        ("sheet_4_roof", generate_sheet_4_roof_structure),
    )
    sheets = []
    for stem, generator in sheet_specs:
        dxf_path, pdf_path = generator(aligned, out_dir / f"{stem}.dxf", out_dir / f"{stem}.pdf")
        sheets.append({"name": stem, "dxf_path": str(dxf_path), "pdf_path": str(pdf_path), "issue": "draft"})"""

replacement = """    sheet_specs = (
        ("01_plan_kolonn_SPDS", "План расположения колонн цеха на отм. 0.000", generate_sheet_1_columns_plan),
        ("02_plan_podkranovyh_balok_SPDS", "Схема подкрановых балок и путей на отм. +6.800", generate_sheet_2_crane_plan),
        ("03_razrez_ceha_1-1_SPDS", "Поперечный разрез цеха 1-1", generate_sheet_3_transverse_section),
        ("04_shema_ferm_i_svyazei_SPDS", "Схема стропильных ферм и связей покрытия", generate_sheet_4_roof_structure),
        ("05_ispolnitelnaya_shema_otkloneniy_SPDS", "Исполнительная геодезическая схема отклонений колонн (СП 70.13330)", generate_sheet_5_executive_deviation_scheme),
    )
    sheets = []
    for idx, (stem, title, generator) in enumerate(sheet_specs, start=1):
        dxf_path = out_dir / f"{stem}.dxf"
        pdf_path = out_dir / f"{stem}.pdf"
        generator(aligned, dxf_path, pdf_path)
        sheets.append({
            "num": idx,
            "name": stem,
            "title": title,
            "dxf_path": str(dxf_path),
            "pdf_path": str(pdf_path),
            "issue": "draft"
        })"""

if target in text:
    text = text.replace(target, replacement)
    # Also ensure album_pdf_path in returned manifest
    text = text.replace('"album_pdf": str(album_pdf),', '"album_pdf": str(album_pdf),\n        "album_pdf_path": str(album_pdf),')
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    print("Updated sheet_specs in spds_full_set.py!")
else:
    print("Target not found")
