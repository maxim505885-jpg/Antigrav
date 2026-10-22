p = "backend/scan2bim/api/app.py"
with open(p, "r", encoding="utf-8") as f:
    text = f.read()

target = 'app.include_router(api, prefix=f"/api/{API_VERSION}")'
replacement = """app.include_router(api, prefix=f"/api/{API_VERSION}")
    from .desktop import router as desktop_router
    app.include_router(desktop_router, prefix=f"/api/{API_VERSION}")"""

if target in text and "desktop_router" not in text:
    text = text.replace(target, replacement, 1)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    print("Desktop router included in app.py!")
else:
    print("Already included or target not found.")
