from pathlib import Path

p = Path("frontend/src/App.tsx")
content = p.read_text(encoding="utf-8")

revit_button = """
                      <button
                        onClick={async () => {
                          try {
                            setBusy(true);
                            const res = await api.openInRevit();
                            alert(res.status === "ok" ? "Autodesk Revit 2027 запущен!" : "Не удалось открыть Revit.");
                          } catch (e: any) {
                            alert("Ошибка запуска Revit: " + e.message);
                          } finally {
                            setBusy(false);
                          }
                        }}
                        disabled={busy}
                      >
                        🏛️ Открыть в Autodesk Revit 2027
                      </button>"""

if 'api.exportBim(cloud.id, "ifc")' in content:
    # insert right after IFC export buttons
    target = 'onClick={() => download(() => api.exportBim(cloud.id, "ifc"),'
    idx = content.find(target)
    if idx != -1:
        btn_end = content.find("</button>", idx) + len("</button>")
        content = content[:btn_end] + revit_button + content[btn_end:]
        print("Added Revit 2027 launcher button to Export tab!")

p.write_text(content, encoding="utf-8")
