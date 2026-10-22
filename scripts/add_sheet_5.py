p = "backend/scan2bim/cad/spds_full_set.py"
with open(p, "r", encoding="utf-8") as f:
    text = f.read()

with open("scripts/sheet_5_code.py", "r", encoding="utf-8") as f:
    sheet5_code = f.read()

# Insert before generate_full_spds_album
target_str = "def generate_full_spds_album("
if target_str in text and "generate_sheet_5_executive_deviation_scheme" not in text:
    new_text = text.replace(target_str, sheet5_code + "\n\n" + target_str)
    # Update sheets list inside generate_full_spds_album
    sheets_str_target = """        {
            "num": 4,
            "title": "Схема стропильных ферм и связей покрытия",
            "dxf_path": str(out_dir / "04_shema_ferm_i_svyazei_SPDS.dxf"),
            "pdf_path": str(out_dir / "04_shema_ferm_i_svyazei_SPDS.pdf"),
            "generator": generate_sheet_4_roof_structure,
        },"""

    sheets_str_replace = """        {
            "num": 4,
            "title": "Схема стропильных ферм и связей покрытия",
            "dxf_path": str(out_dir / "04_shema_ferm_i_svyazei_SPDS.dxf"),
            "pdf_path": str(out_dir / "04_shema_ferm_i_svyazei_SPDS.pdf"),
            "generator": generate_sheet_4_roof_structure,
        },
        {
            "num": 5,
            "title": "Исполнительная схема отклонений колонн (СП 70.13330)",
            "dxf_path": str(out_dir / "05_ispolnitelnaya_shema_otkloneniy_SPDS.dxf"),
            "pdf_path": str(out_dir / "05_ispolnitelnaya_shema_otkloneniy_SPDS.pdf"),
            "generator": generate_sheet_5_executive_deviation_scheme,
        },"""
    new_text = new_text.replace(sheets_str_target, sheets_str_replace)
    with open(p, "w", encoding="utf-8") as f:
        f.write(new_text)
    print("Successfully added Sheet 5 (Executive deviation scheme) to spds_full_set.py!")
else:
    print("Already present or target not found.")
