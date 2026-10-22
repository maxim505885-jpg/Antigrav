from pathlib import Path

p = Path("frontend/src/App.tsx")
content = p.read_text(encoding="utf-8")

old_tabs_type = 'type Tab = "section" | "recognition" | "learning" | "export";'
new_tabs_type = 'type Tab = "section" | "recognition" | "learning" | "export" | "registration";'

if old_tabs_type in content:
    content = content.replace(old_tabs_type, new_tabs_type, 1)
    print("1. Added registration to Tab type")

old_tab_labels = """const TAB_LABELS: Record<Tab, string> = {
  section: "Сечение",
  recognition: "Распознавание",
  learning: "Обучение",
  export: "Экспорт",
};"""

# Or check what TAB_LABELS actually looks like in file
if "learning:" in content and "export:" in content:
    # replace the tab labels block
    idx = content.find("const TAB_LABELS")
    if idx != -1:
        end_idx = content.find("};", idx)
        block = content[idx:end_idx+2]
        new_block = block[:-2] + '  registration: "Сшивка ReCap",\n};'
        content = content.replace(block, new_block, 1)
        print("2. Added registration to TAB_LABELS")

# 3. Add to tabs array in JSX
old_tabs_array = '(["section", "recognition", "learning", "export"] as Tab[])'
new_tabs_array = '(["section", "recognition", "learning", "export", "registration"] as Tab[])'
if old_tabs_array in content:
    content = content.replace(old_tabs_array, new_tabs_array, 1)
    print("3. Added registration to JSX tabs array")

# 4. Add registration tab content
reg_ui_snippet = """
            {tab === "registration" && (
              <div className="tab-body">
                <div className="panel-title">
                  <span>Сшивка сканов и экспорт в Autodesk ReCap</span>
                </div>
                <p className="hint">
                  Совмещение нескольких стоянок сканера по алгоритму жесткого ICP (Kabsch SVD + KDTree) с контролем среднеквадратичной ошибки (RMSE в мм) и формированием проекта ReCap.
                </p>
                <div className="button-row" style={{ marginTop: 12 }}>
                  <button
                    className="primary-button"
                    onClick={async () => {
                      if (!cloud) {
                        alert("Сначала выберите опорное облако проекта слева.");
                        return;
                      }
                      try {
                        setBusy(true);
                        const res = await api.matchCloudsIcp(cloud.id, cloud.id, 10000, 25);
                        alert(`Сшивка выполнена! Сходимость: ${res.converged ? "ДА" : "НЕТ"}\\nНевязка RMSE: ${res.rmse_mm.toFixed(2)} мм\\nИтераций: ${res.iterations}`);
                      } catch (e: any) {
                        alert("Ошибка сшивки: " + e.message);
                      } finally {
                        setBusy(false);
                      }
                    }}
                    disabled={busy || !cloud}
                  >
                    🔗 Запустить сшивку ICP (Kabsch SVD)
                  </button>
                  <button
                    onClick={async () => {
                      try {
                        setBusy(true);
                        const res = await api.openInReCap();
                        alert(res.status === "ok" ? "Autodesk ReCap запущен!" : "Не удалось открыть ReCap.");
                      } catch (e: any) {
                        alert("Ошибка: " + e.message);
                      } finally {
                        setBusy(false);
                      }
                    }}
                    disabled={busy}
                  >
                    🚀 Запустить Autodesk ReCap
                  </button>
                </div>
              </div>
            )}
"""

if '{tab === "export" && (' in content:
    content = content.replace('{tab === "export" && (', reg_ui_snippet + '\n            {tab === "export" && (', 1)
    print("4. Added registration tab body JSX")

p.write_text(content, encoding="utf-8")
print("App.tsx update complete!")
