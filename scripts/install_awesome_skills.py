import os
import shutil
import re
from pathlib import Path

source_repo = Path(r"C:\Users\maxim\.gemini\antigravity\scratch\awesome-claude-skills")
global_target = Path(r"C:\Users\maxim\.gemini\config\skills")
user_antigravity_target = Path(r"C:\Users\maxim\.gemini\antigravity\skills")
project_target = Path(r"C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\intelligent-scan-to-bim\.agents\skills")

targets = [global_target, user_antigravity_target, project_target]
for t in targets:
    t.mkdir(parents=True, exist_ok=True)

skills_installed = []

for root, dirs, files in os.walk(source_repo):
    if ".git" in root:
        continue
    for file in files:
        if not file.endswith(".md"):
            continue
        if file.upper() in ["README.MD", "INDEX.MD", "CONTRIBUTING.MD", "LICENSE.MD"]:
            continue

        file_path = Path(root) / file
        content = file_path.read_text(encoding="utf-8")

        # Parse YAML frontmatter
        match = re.search(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        skill_name = file_path.stem
        if match:
            fm = match.group(1)
            name_m = re.search(r"^name:\s*([^\n\r]+)", fm, re.MULTILINE)
            if name_m:
                skill_name = name_m.group(1).strip().strip("'\"")

        # Sanitize skill name
        skill_name = re.sub(r"[^a-zA-Z0-9_-]", "-", skill_name).lower().strip("-")
        if not skill_name:
            continue

        # If frontmatter doesn't have name or description, ensure standard YAML frontmatter
        if not match:
            first_header = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
            title = first_header.group(1).strip() if first_header else skill_name
            content = f"---\nname: {skill_name}\ndescription: {title}\n---\n\n" + content
        else:
            fm = match.group(1)
            if "description:" not in fm:
                content = content.replace(f"name: {skill_name}", f"name: {skill_name}\ndescription: Specialized skill for {skill_name}")

        # Install into all target locations
        for target_dir in targets:
            skill_folder = target_dir / skill_name
            skill_folder.mkdir(parents=True, exist_ok=True)
            skill_file = skill_folder / "SKILL.md"
            skill_file.write_text(content, encoding="utf-8")

        skills_installed.append((skill_name, file_path.parent.name))

print(f"Total skills successfully installed: {len(skills_installed)}")
print("\nSample installed skills (first 25):")
for name, cat in skills_installed[:25]:
    print(f"  [{cat}] {name}")
