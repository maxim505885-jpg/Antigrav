from pathlib import Path

p = Path("backend/scan2bim/api/app.py")
content = p.read_text(encoding="utf-8")

target = """    app.include_router(api, prefix=f"/api/{API_VERSION}")
    from .desktop import router as desktop_router
    app.include_router(desktop_router, prefix=f"/api/{API_VERSION}")"""

replacement = """    app.include_router(api, prefix=f"/api/{API_VERSION}")
    from .desktop import router as desktop_router
    app.include_router(desktop_router, prefix=f"/api/{API_VERSION}")
    from .registration import router as registration_router
    app.include_router(registration_router, prefix=f"/api/{API_VERSION}")"""

if target in content:
    new_content = content.replace(target, replacement, 1)
    p.write_text(new_content, encoding="utf-8")
    print("Successfully added registration router!")
else:
    print("Target not found, check lines:")
