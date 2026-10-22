from pathlib import Path

p = Path("frontend/src/api.ts")
content = p.read_text(encoding="utf-8")

old_code = """  exportRecapProject: (projectName: string, stations: any[]) =>
    request<{ status: string; output_path: string; stations_count: number }>("/registration/export-recap", {
      method: "POST",
      body: JSON.stringify({ project_name: projectName, stations }),
    }),
};"""

new_code = """  exportRecapProject: (projectName: string, stations: any[]) =>
    request<{ status: string; output_path: string; stations_count: number }>("/registration/export-recap", {
      method: "POST",
      body: JSON.stringify({ project_name: projectName, stations }),
    }),

  // AI Workshop Construction Expert Agent
  askWorkshopExpert: (query: string, cloudContext?: any) =>
    request<{
      topic: string;
      answer: string;
      recommendations: string[];
      referenced_norms: string[];
      cad_shortcut_tips: string[];
    }>("/expert/ask", {
      method: "POST",
      body: JSON.stringify({ query, cloud_context: cloudContext }),
    }),
};"""

if old_code in content:
    p.write_text(content.replace(old_code, new_code, 1), encoding="utf-8")
    print("Added askWorkshopExpert to api.ts!")
else:
    print("old_code not matched in api.ts, manual search...")
    if "exportRecapProject:" in content:
        lines = content.splitlines()
        for idx, line in enumerate(lines):
            if "exportRecapProject:" in line and "};" in lines[idx+4]:
                lines[idx+4] = """    }),

  // AI Workshop Construction Expert Agent
  askWorkshopExpert: (query: string, cloudContext?: any) =>
    request<{
      topic: string;
      answer: string;
      recommendations: string[];
      referenced_norms: string[];
      cad_shortcut_tips: string[];
    }>("/expert/ask", {
      method: "POST",
      body: JSON.stringify({ query, cloud_context: cloudContext }),
    }),
};"""
                break
        p.write_text("\n".join(lines), encoding="utf-8")
        print("Replaced via lines indexing!")
