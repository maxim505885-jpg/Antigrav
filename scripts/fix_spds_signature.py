p = "backend/scan2bim/cad/spds_full_set.py"
with open(p, "r", encoding="utf-8") as f:
    text = f.read()

old_sig = """def generate_full_spds_album(
    elements: list[dict[str, Any]],
    output_dir: str | Path,
    project_title: str = "Производственный корпус 1.rcs",
) -> dict[str, Any]:"""

new_sig = """def generate_full_spds_album(
    elements: list[dict[str, Any]],
    output_dir: str | Path | None = None,
    project_title: str = "Производственный корпус 1.rcs",
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    out_dir = Path(output_dir or out_dir)"""

if "out_dir = Path(output_dir)" in text:
    text = text.replace("out_dir = Path(output_dir)", "out_dir = Path(output_dir or out_dir)")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    print("Fixed out_dir alias!")
elif "out_dir = Path(out_dir)" in text:
    text = text.replace("out_dir = Path(out_dir)", "out_dir = Path(output_dir or out_dir)")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    print("Fixed out_dir alias!")
