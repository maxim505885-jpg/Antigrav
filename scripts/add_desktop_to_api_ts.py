p = "frontend/src/api.ts"
with open(p, "r", encoding="utf-8") as f:
    text = f.read()

desktop_api_methods = """
  // Desktop OS integrations
  desktopStatus: () => request<{ platform: string; autocad_available: boolean; recap_available: boolean }>("/desktop/status"),
  openInAutoCAD: (path: string) => request<{ status: string; app: string }>("/desktop/open-autocad", { method: "POST", body: JSON.stringify({ path }) }),
  openInReCap: (path?: string) => request<{ status: string; app: string }>("/desktop/open-recap", { method: "POST", body: JSON.stringify({ path: path || "" }) }),
  openInExplorer: (path: string) => request<{ status: string; path: string }>("/desktop/open-explorer", { method: "POST", body: JSON.stringify({ path }) }),
  pickFileWindows: (title?: string) => request<{ cancelled: boolean; path?: string; filename?: string; size_bytes?: number; extension?: string }>("/desktop/pick-file", { method: "POST", body: JSON.stringify({ title: title || "Выберите файл облака точек" }) }),
};"""

if "desktopStatus:" not in text:
    # replace the closing "};" of api object
    last_brace_idx = text.rfind("};")
    if last_brace_idx != -1:
        text = text[:last_brace_idx] + desktop_api_methods + text[last_brace_idx + 2:]
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        print("Successfully added desktop methods to api.ts!")
    else:
        print("Closing brace not found in api.ts")
else:
    print("Desktop methods already present in api.ts")
