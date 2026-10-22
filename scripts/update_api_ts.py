p = "frontend/src/api.ts"
with open(p, "r", encoding="utf-8") as f:
    text = f.read()

target = """  exportSpdsAlbum: (cloudId: string) =>
    download(`/clouds/${encodeURIComponent(cloudId)}/spds-album.zip`, "GET", "spds-album-draft.zip"),"""

replacement = """  exportSpdsAlbum: (cloudId: string) =>
    download(`/clouds/${encodeURIComponent(cloudId)}/spds-album.zip`, "GET", "spds-album-draft.zip"),
  exportSpdsAlbumPdf: (cloudId: string) =>
    download(`/clouds/${encodeURIComponent(cloudId)}/spds-album.pdf`, "GET", "ALBUM_RD_KR_KM_SPDS.pdf"),"""

text = text.replace(target.replace("\r\n", "\n"), replacement.replace("\r\n", "\n"))
with open(p, "w", encoding="utf-8") as f:
    f.write(text)
print("Updated api.ts with exportSpdsAlbumPdf!")
