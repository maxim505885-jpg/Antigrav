p = "backend/scan2bim/cad/spds_full_set.py"
with open(p, "r", encoding="utf-8") as f:
    text = f.read()

target = "def generate_full_spds_album(elements: list[dict[str, Any]], out_dir: str | Path) -> dict[str, Any]:\n    out_dir = Path(out_dir)"
replacement = """def generate_full_spds_album(elements: list[dict[str, Any]], out_dir: str | Path | None = None, output_dir: str | Path | None = None, project_title: str = "Производственный корпус") -> dict[str, Any]:
    out_dir = Path(output_dir if output_dir is not None else out_dir)"""

if target in text:
    text = text.replace(target, replacement)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    print("Fixed generate_full_spds_album signature!")
else:
    print("Target not found")
