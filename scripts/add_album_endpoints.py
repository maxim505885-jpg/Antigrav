target = """        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return FileResponse(path, media_type="application/pdf", filename=path.name)"""

replacement = """        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return FileResponse(path, media_type="application/pdf", filename=path.name)

    @api.get("/clouds/{cloud_id}/spds-album.pdf")
    def spds_album_pdf(cloud_id: str):
        from ..cad.spds_full_set import generate_full_spds_album
        cloud = _cloud(cloud_id)
        project = _project(cloud["project_id"])
        elements = list_elements(cloud_id)
        export_id, folder = new_export_dir(cloud["project_id"], f"spds_album_{cloud_id[:8]}")
        manifest = generate_full_spds_album(
            elements=elements,
            output_dir=folder,
            project_title=project["name"],
        )
        album_path = Path(manifest["album_pdf_path"])
        return FileResponse(album_path, media_type="application/pdf", filename=album_path.name)

    @api.get("/clouds/{cloud_id}/spds-album.zip")
    def spds_album_zip(cloud_id: str):
        from ..cad.spds_full_set import generate_full_spds_album
        cloud = _cloud(cloud_id)
        project = _project(cloud["project_id"])
        elements = list_elements(cloud_id)
        export_id, folder = new_export_dir(cloud["project_id"], f"spds_album_{cloud_id[:8]}")
        manifest = generate_full_spds_album(
            elements=elements,
            output_dir=folder,
            project_title=project["name"],
        )
        zip_path = folder / "ALBUM_RD_KR_KM_SPDS.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for s in manifest["sheets"]:
                dxf_file = Path(s["dxf_path"])
                pdf_file = Path(s["pdf_path"])
                if dxf_file.exists():
                    zf.write(dxf_file, arcname=dxf_file.name)
                if pdf_file.exists():
                    zf.write(pdf_file, arcname=pdf_file.name)
            alb_pdf = Path(manifest["album_pdf_path"])
            if alb_pdf.exists():
                zf.write(alb_pdf, arcname=alb_pdf.name)
        return FileResponse(zip_path, media_type="application/zip", filename=zip_path.name)"""

p = "backend/scan2bim/api/app.py"
with open(p, "r", encoding="utf-8") as f:
    text = f.read()

# Normalize CRLF
norm_text = text.replace("\r\n", "\n")
norm_target = target.replace("\r\n", "\n")
norm_replacement = replacement.replace("\r\n", "\n")

if norm_target in norm_text:
    new_text = norm_text.replace(norm_target, norm_replacement, 1)
    with open(p, "w", encoding="utf-8") as f:
        f.write(new_text)
    print("Successfully added spds-album endpoints to app.py!")
else:
    print("Target pattern not found in app.py")
