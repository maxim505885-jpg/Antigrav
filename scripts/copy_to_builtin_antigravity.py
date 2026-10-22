import shutil
from pathlib import Path

source_skills = Path(r"C:\Users\maxim\.gemini\config\skills")
builtin_target = Path(r"C:\Users\maxim\.gemini\antigravity\builtin\skills")
antigravity_skills = Path(r"C:\Users\maxim\.gemini\antigravity\skills")

builtin_target.mkdir(parents=True, exist_ok=True)
antigravity_skills.mkdir(parents=True, exist_ok=True)

copied_builtin = 0
for skill_dir in source_skills.iterdir():
    if not skill_dir.is_dir():
        continue
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        continue

    # Copy to builtin
    dest_builtin = builtin_target / skill_dir.name
    dest_builtin.mkdir(parents=True, exist_ok=True)
    for item in skill_dir.glob("**/*"):
        rel = item.relative_to(skill_dir)
        target_item = dest_builtin / rel
        if item.is_dir():
            target_item.mkdir(parents=True, exist_ok=True)
        else:
            target_item.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target_item)

    # Copy to antigravity/skills
    dest_ag = antigravity_skills / skill_dir.name
    dest_ag.mkdir(parents=True, exist_ok=True)
    for item in skill_dir.glob("**/*"):
        rel = item.relative_to(skill_dir)
        target_item = dest_ag / rel
        if item.is_dir():
            target_item.mkdir(parents=True, exist_ok=True)
        else:
            target_item.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target_item)

    copied_builtin += 1

print(f"Copied {copied_builtin} skills into C:\\Users\\maxim\\.gemini\\antigravity\\builtin\\skills and C:\\Users\\maxim\\.gemini\\antigravity\\skills")
