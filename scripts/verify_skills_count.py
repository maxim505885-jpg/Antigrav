from pathlib import Path

g_skills = len(list(Path(r"C:\Users\maxim\.gemini\config\skills").glob("*")))
p_skills = len(list(Path(r"C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\intelligent-scan-to-bim\.agents\skills").glob("*")))
agents = len(list(Path(r"C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\intelligent-scan-to-bim\.agents\agents").glob("*.md")))
rules = len(list(Path(r"C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\intelligent-scan-to-bim\.agents\rules").rglob("*.md")))

print(f"GLOBAL_SKILLS: {g_skills}")
print(f"PROJECT_SKILLS: {p_skills}")
print(f"AGENTS: {agents}")
print(f"RULES: {rules}")
