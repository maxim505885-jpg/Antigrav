from pathlib import Path

p = Path("backend/scan2bim/api/app.py")
content = p.read_text(encoding="utf-8")

target = """    from .registration import router as registration_router
    app.include_router(registration_router, prefix=f"/api/{API_VERSION}")"""

replacement = """    from .registration import router as registration_router
    app.include_router(registration_router, prefix=f"/api/{API_VERSION}")
    from .expert_agent import router as expert_agent_router
    app.include_router(expert_agent_router, prefix=f"/api/{API_VERSION}")"""

if target in content:
    new_content = content.replace(target, replacement, 1)
    p.write_text(new_content, encoding="utf-8")
    print("Successfully added expert_agent router to app.py!")
else:
    print("Target not found in app.py!")
