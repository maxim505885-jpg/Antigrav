"""Сквозной экспорт чистового комплекта документации и BIM-модели цеха.

Генерирует:
1. workshop_bim_model.json - BIM JSON 1.0 модель (валидирована по scan2bim.bim-1.0.schema.json)
2. workshop_model.ifc - IFC4 модель с набором свойств Pset_ScanToBIM
3. workshop_columns_plan.dxf - 2D монтажный план колонн с марками и ведомостью (AutoCAD)
4. workshop_columns_plan.pdf - Векторный лист А3 чертежа
5. manifest.json - Контрольные суммы (SHA-256) и метаданные комплекта сдачи
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import ezdxf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from scan2bim.bim.ifc import export_ifc
from scan2bim.bim.model import build_model, validate_bim_model
from scan2bim.cad.dxf import export_structural_plan_dxf
from scan2bim.cad.pdf import export_structural_plan_pdf


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud-id", default="2621e5a320df49949d04aa1b7399539e", help="ID облака точек в базе")
    parser.add_argument("--out", default=str(ROOT / "data" / "output" / "workshop_release"), help="Выходной каталог")
    args = parser.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    db_path = ROOT / "data" / "scan2bim.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cloud_row = conn.execute("SELECT * FROM clouds WHERE id=?", (args.cloud_id,)).fetchone()
        if not cloud_row:
            raise ValueError(f"Облако {args.cloud_id} не найдено в {db_path}")
        cloud = dict(cloud_row)

        project_row = conn.execute("SELECT * FROM projects WHERE id=?", (cloud["project_id"],)).fetchone()
        project = dict(project_row) if project_row else {"id": cloud["project_id"], "name": cloud["name"]}

        element_rows = conn.execute(
            "SELECT * FROM elements WHERE cloud_id=? AND review_status != 'rejected'",
            (args.cloud_id,),
        ).fetchall()

    elements = []
    for r in element_rows:
        el = dict(r)
        el["geometry"] = json.loads(el["geometry_json"])
        el["bbox"] = json.loads(el["bbox_json"]) if el.get("bbox_json") else None
        el["dimensions"] = json.loads(el["dimensions_json"]) if el.get("dimensions_json") else {}
        elements.append(el)

    print(f"=== Intelligent Scan-to-BIM: Выпуск комплекта цеха ===")
    print(f"Облако: {cloud['name']} (ID: {cloud['id'][:8]}...)")
    print(f"Элементов в модели: {len(elements)}")

    # 1. Извлечение отметок уровней
    metadata = json.loads(cloud.get("metadata_json") or "{}")
    levels = metadata.get("recognition", {}).get("levels", [])
    print(f"Высотных отметок: {len(levels)}")

    # 2. Построение и валидация BIM модели
    bim_model = build_model(project, cloud, elements, levels)
    validate_bim_model(bim_model)

    bim_json_path = out_dir / "workshop_bim_model.json"
    bim_json_path.write_text(json.dumps(bim_model, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[1/4] BIM JSON: {bim_json_path.name} ({bim_json_path.stat().st_size / 1024:.1f} KB)")

    # 3. Экспорт IFC4
    ifc_path = out_dir / "workshop_model.ifc"
    export_ifc(bim_model, ifc_path, project_name=project["name"])
    print(f"[2/4] IFC4 Model: {ifc_path.name} ({ifc_path.stat().st_size / 1024:.1f} KB)")

    # 4. Экспорт DXF для AutoCAD
    dxf_path = out_dir / "workshop_columns_plan.dxf"
    export_structural_plan_dxf(elements, dxf_path, "columns", project_name=project["name"], issue_mode="draft")
    doc = ezdxf.readfile(dxf_path)
    audit = doc.audit()
    assert len(audit.errors) == 0, f"DXF содержит ошибки: {audit.errors}"
    print(f"[3/4] AutoCAD DXF: {dxf_path.name} ({dxf_path.stat().st_size / 1024:.1f} KB, Audit OK)")

    # 5. Экспорт векторного PDF A3
    pdf_path = out_dir / "workshop_columns_plan.pdf"
    export_structural_plan_pdf(elements, pdf_path, drawing_type="columns", project_name=project["name"], issue_mode="draft")
    print(f"[4/4] Векторный PDF A3: {pdf_path.name} ({pdf_path.stat().st_size / 1024:.1f} KB)")

    # 6. Манифест сдачи
    manifest = {
        "project": project["name"],
        "cloud_id": cloud["id"],
        "source_cloud": cloud.get("source_path", "1.rcs"),
        "total_elements": len(elements),
        "levels_count": len(levels),
        "files": {
            "bim_model_json": {"path": bim_json_path.name, "sha256": sha256(bim_json_path), "bytes": bim_json_path.stat().st_size},
            "ifc_model": {"path": ifc_path.name, "sha256": sha256(ifc_path), "bytes": ifc_path.stat().st_size},
            "autocad_dxf": {"path": dxf_path.name, "sha256": sha256(dxf_path), "bytes": dxf_path.stat().st_size},
            "drawing_pdf": {"path": pdf_path.name, "sha256": sha256(pdf_path), "bytes": pdf_path.stat().st_size},
        },
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Манифест сохранён: {manifest_path.name}")
    print(f"=== Комплект успешно сформирован в {out_dir} ===")


if __name__ == "__main__":
    main()
