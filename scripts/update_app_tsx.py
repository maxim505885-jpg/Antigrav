p = "frontend/src/App.tsx"
with open(p, "r", encoding="utf-8") as f:
    text = f.read()

target = """                    <div className="button-row">
                      <button onClick={() => download(() => api.exportSpdsAlbum(cloud.id), "Экспорт альбома СПДС")} disabled={busy}>
                        Скачать альбом СПДС
                      </button>
                    </div>"""

replacement = """                    <div className="button-row">
                      <button onClick={() => download(() => api.exportSpdsAlbumPdf(cloud.id), "Экспорт альбома СПДС (PDF)")} disabled={busy} className="primary-button">
                        📄 Скачать альбом РД КР/КМ (ГОСТ PDF)
                      </button>
                      <button onClick={() => download(() => api.exportSpdsAlbum(cloud.id), "Экспорт чертежей СПДС (ZIP/DXF)")} disabled={busy}>
                        📦 Скачать чертежи DWG/DXF (AutoCAD)
                      </button>
                    </div>"""

text = text.replace(target.replace("\r\n", "\n"), replacement.replace("\r\n", "\n"))
with open(p, "w", encoding="utf-8") as f:
    f.write(text)
print("Updated App.tsx with direct PDF and ZIP buttons!")
