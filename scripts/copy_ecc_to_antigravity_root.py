import shutil
from pathlib import Path

ecc_dir = Path(r"C:\Users\maxim\.gemini\antigravity\scratch\ECC")
antigravity_dir = Path(r"C:\Users\maxim\.gemini\antigravity")

# Agents
src_agents = ecc_dir / "agents"
dest_agents = antigravity_dir / "agents"
dest_agents.mkdir(parents=True, exist_ok=True)
for item in src_agents.glob("*.md"):
    shutil.copy2(item, dest_agents / item.name)

# Rules
src_rules = ecc_dir / "rules"
dest_rules = antigravity_dir / "rules"
dest_rules.mkdir(parents=True, exist_ok=True)
for item in src_rules.glob("**/*"):
    if item.is_file():
        rel = item.relative_to(src_rules)
        target = dest_rules / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)

# GEMINI.md
gemini_md = ecc_dir / ".gemini" / "GEMINI.md"
if gemini_md.exists():
    shutil.copy2(gemini_md, antigravity_dir / "GEMINI.md")

print("Copied all ECC agents, rules, and GEMINI.md directly into Antigravity root!")
