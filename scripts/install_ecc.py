import os
import shutil
from pathlib import Path

ecc_dir = Path(r"C:\Users\maxim\.gemini\antigravity\scratch\ECC")

# Target roots
global_config = Path(r"C:\Users\maxim\.gemini\config")
user_antigravity = Path(r"C:\Users\maxim\.gemini\antigravity")
project_root = Path(r"C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\intelligent-scan-to-bim")

skill_targets = [
    global_config / "skills",
    user_antigravity / "skills",
    project_root / ".agents" / "skills",
    project_root / ".agent" / "skills",
]

agent_targets = [
    global_config / "agents",
    user_antigravity / "agents",
    project_root / ".agents" / "agents",
    project_root / ".agent" / "agents",
]

rule_targets = [
    global_config / "rules",
    user_antigravity / "rules",
    project_root / ".agents" / "rules",
    project_root / ".agent" / "rules",
]

for t_list in [skill_targets, agent_targets, rule_targets]:
    for t in t_list:
        t.mkdir(parents=True, exist_ok=True)

# 1. Install skills
src_skills = ecc_dir / "skills"
skills_installed = 0
for skill_path in src_skills.iterdir():
    if not skill_path.is_dir():
        continue
    skill_name = skill_path.name
    # Check if SKILL.md exists
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        continue

    for target_dir in skill_targets:
        dest = target_dir / skill_name
        dest.mkdir(parents=True, exist_ok=True)
        # copy all files in skill directory (SKILL.md, scripts, references, etc.)
        for item in skill_path.glob("**/*"):
            rel = item.relative_to(skill_path)
            dest_item = dest / rel
            if item.is_dir():
                dest_item.mkdir(parents=True, exist_ok=True)
            else:
                dest_item.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest_item)
    skills_installed += 1

print(f"Installed {skills_installed} skills from ECC.")

# 2. Install agents
src_agents = ecc_dir / "agents"
agents_installed = 0
for item in src_agents.glob("*.md"):
    if item.name.upper() in ["README.MD"]:
        continue
    for target_dir in agent_targets:
        shutil.copy2(item, target_dir / item.name)
    agents_installed += 1

print(f"Installed {agents_installed} agents from ECC.")

# 3. Install rules
src_rules = ecc_dir / "rules"
rules_installed = 0
for rule_item in src_rules.glob("**/*"):
    if rule_item.is_file() and rule_item.suffix in [".md", ".json"]:
        rel = rule_item.relative_to(src_rules)
        for target_dir in rule_targets:
            dest_file = target_dir / rel
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(rule_item, dest_file)
        rules_installed += 1

print(f"Installed {rules_installed} rules from ECC.")

# 4. Copy GEMINI.md from ECC
gemini_md = ecc_dir / ".gemini" / "GEMINI.md"
if gemini_md.exists():
    for target_root in [global_config, project_root]:
        dest_gemini = target_root / "GEMINI_ECC.md"
        shutil.copy2(gemini_md, dest_gemini)
    print("ECC GEMINI guidelines installed as GEMINI_ECC.md.")

print("All ECC components successfully installed and integrated into Antigravity!")
