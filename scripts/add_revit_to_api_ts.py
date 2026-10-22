from pathlib import Path

p = Path("frontend/src/api.ts")
content = p.read_text(encoding="utf-8")

old_part = 'desktopStatus: () => request<{ platform: string; autocad_available: boolean; recap_available: boolean }>("/desktop/status"),'
new_part = 'desktopStatus: () => request<{ platform: string; autocad_available: boolean; recap_available: boolean; revit_available?: boolean }>("/desktop/status"),'

content = content.replace(old_part, new_part, 1)

old_recap = 'openInReCap: (path?: string) => request<{ status: string; app: string }>("/desktop/open-recap", { method: "POST", body: JSON.stringify({ path: path || "" }) }),'
new_revit = 'openInReCap: (path?: string) => request<{ status: string; app: string }>("/desktop/open-recap", { method: "POST", body: JSON.stringify({ path: path || "" }) }),\n  openInRevit: (path?: string) => request<{ status: string; app: string }>("/desktop/open-revit", { method: "POST", body: JSON.stringify({ path: path || "" }) }),'

content = content.replace(old_recap, new_revit, 1)

p.write_text(content, encoding="utf-8")
print("Added openInRevit to api.ts!")
