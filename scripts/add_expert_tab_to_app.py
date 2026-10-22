from pathlib import Path

p = Path("frontend/src/App.tsx")
content = p.read_text(encoding="utf-8")

old_tabs_type = 'type Tab = "section" | "recognition" | "learning" | "export" | "registration";'
new_tabs_type = 'type Tab = "section" | "recognition" | "learning" | "export" | "registration" | "expert";'

if old_tabs_type in content:
    content = content.replace(old_tabs_type, new_tabs_type, 1)
    print("1. Added expert to Tab type")

if 'registration: "Сшивка ReCap",' in content:
    content = content.replace('registration: "Сшивка ReCap",', 'registration: "Сшивка ReCap",\n  expert: "Агент-Конструктор",', 1)
    print("2. Added expert to TAB_LABELS")

old_tabs_array = '(["section", "recognition", "learning", "export", "registration"] as Tab[])'
new_tabs_array = '(["section", "recognition", "learning", "export", "registration", "expert"] as Tab[])'
if old_tabs_array in content:
    content = content.replace(old_tabs_array, new_tabs_array, 1)
    print("3. Added expert to JSX tabs array")

expert_ui_snippet = """
            {tab === "expert" && (
              <div className="tab-body">
                <div className="panel-title">
                  <span>🧠 ИИ Ассистент-Конструктор по промышленным цехам (СПДС / ГОСТ / СП 16 / СП 70)</span>
                </div>
                <p className="hint">
                  Инженерный агент обладает глубокими знаниями конструктива каркасных цехов, кранового оборудования, серий ферм, раскладки связей и правил оформления рабочей документации.
                </p>

                <div style={{ display: "flex", gap: "8px", margin: "14px 0" }}>
                  <input
                    type="text"
                    id="expert-query-input"
                    placeholder="Спросите инженера (например: 'Какие допуски на рельс КР-70?', 'Как завязать связи ферм?')..."
                    style={{ flex: 1, padding: "8px 12px", background: "#1e1e24", border: "1px solid #333", borderRadius: "4px", color: "#fff" }}
                    onKeyDown={async (e) => {
                      if (e.key === "Enter") {
                        const target = e.currentTarget;
                        const val = target.value.trim();
                        if (!val) return;
                        try {
                          setBusy(true);
                          const res = await api.askWorkshopExpert(val, { columns_count: 233 });
                          const outDiv = document.getElementById("expert-answer-box");
                          if (outDiv) {
                            outDiv.innerHTML = `
                              <div style="background: #18181e; border-left: 4px solid #3b82f6; padding: 14px; border-radius: 4px; margin-top: 12px;">
                                <h3 style="margin-top: 0; color: #60a5fa;">${res.topic}</h3>
                                <div style="white-space: pre-wrap; line-height: 1.6;">${res.answer}</div>
                                <h4 style="margin-bottom: 6px; color: #f59e0b;">Нормативные документы:</h4>
                                <ul>${res.referenced_norms.map(n => `<li><b>${n}</b></li>`).join("")}</ul>
                                <h4 style="margin-bottom: 6px; color: #10b981;">Рекомендации и допуски:</h4>
                                <ul>${res.recommendations.map(r => `<li>${r}</li>`).join("")}</ul>
                                <h4 style="margin-bottom: 6px; color: #a78bfa;">Советы по черчению в AutoCAD:</h4>
                                <ul>${res.cad_shortcut_tips.map(t => `<li>${t}</li>`).join("")}</ul>
                              </div>
                            `;
                          }
                        } catch (err: any) {
                          alert("Ошибка связи с агентом: " + err.message);
                        } finally {
                          setBusy(false);
                        }
                      }
                    }}
                  />
                  <button
                    className="primary-button"
                    onClick={async () => {
                      const inp = document.getElementById("expert-query-input") as HTMLInputElement;
                      if (!inp || !inp.value.trim()) return;
                      const val = inp.value.trim();
                      try {
                        setBusy(true);
                        const res = await api.askWorkshopExpert(val, { columns_count: 233 });
                        const outDiv = document.getElementById("expert-answer-box");
                        if (outDiv) {
                          outDiv.innerHTML = `
                            <div style="background: #18181e; border-left: 4px solid #3b82f6; padding: 14px; border-radius: 4px; margin-top: 12px;">
                              <h3 style="margin-top: 0; color: #60a5fa;">${res.topic}</h3>
                              <div style="white-space: pre-wrap; line-height: 1.6;">${res.answer}</div>
                              <h4 style="margin-bottom: 6px; color: #f59e0b;">Нормативные документы:</h4>
                              <ul>${res.referenced_norms.map(n => `<li><b>${n}</b></li>`).join("")}</ul>
                              <h4 style="margin-bottom: 6px; color: #10b981;">Рекомендации и допуски:</h4>
                              <ul>${res.recommendations.map(r => `<li>${r}</li>`).join("")}</ul>
                              <h4 style="margin-bottom: 6px; color: #a78bfa;">Советы по черчению в AutoCAD:</h4>
                              <ul>${res.cad_shortcut_tips.map(t => `<li>${t}</li>`).join("")}</ul>
                            </div>
                          `;
                        }
                      } catch (err: any) {
                        alert("Ошибка связи с агентом: " + err.message);
                      } finally {
                        setBusy(false);
                      }
                    }}
                    disabled={busy}
                  >
                    Задать вопрос
                  </button>
                </div>

                <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", marginBottom: "12px" }}>
                  <button onClick={() => { const inp = document.getElementById("expert-query-input") as HTMLInputElement; if (inp) { inp.value = "Как выполнить привязку колонн цеха к осям?"; } }}>
                    📌 Привязка колонн
                  </button>
                  <button onClick={() => { const inp = document.getElementById("expert-query-input") as HTMLInputElement; if (inp) { inp.value = "Какие требования и допуски к рельсам крана КР-70?"; } }}>
                    🚂 Рельсы КР-70
                  </button>
                  <button onClick={() => { const inp = document.getElementById("expert-query-input") as HTMLInputElement; if (inp) { inp.value = "Как устроены стропильные фермы ФС-30?"; } }}>
                    🏗️ Фермы покрытия
                  </button>
                  <button onClick={() => { const inp = document.getElementById("expert-query-input") as HTMLInputElement; if (inp) { inp.value = "Система связей каркаса цеха"; } }}>
                    ⚡ Связи каркаса
                  </button>
                  <button onClick={() => { const inp = document.getElementById("expert-query-input") as HTMLInputElement; if (inp) { inp.value = "Отметки верха фундамента под колонны"; } }}>
                    🏛️ Фундаменты
                  </button>
                </div>

                <div id="expert-answer-box">
                  <div style={{ padding: "16px", background: "#141418", borderRadius: "4px", color: "#888", fontSize: "14px" }}>
                    💡 Выберите один из быстрых вопросов выше или введите свой вопрос. Агент подскажет нормативы СП/ГОСТ, правильную привязку элементов, допуски монтажа и нюансы для AutoCAD 2026.
                  </div>
                </div>
              </div>
            )}
"""

if '{tab === "registration" && (' in content:
    content = content.replace('{tab === "registration" && (', expert_ui_snippet + '\n            {tab === "registration" && (', 1)
    print("4. Added expert tab body JSX")

p.write_text(content, encoding="utf-8")
print("App.tsx update complete!")
