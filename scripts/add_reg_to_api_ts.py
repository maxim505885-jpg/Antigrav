from pathlib import Path

p = Path("frontend/src/api.ts")
content = p.read_text(encoding="utf-8")

old_part = """  pickFileWindows: (title?: string) => request<{ cancelled: boolean; path?: string; filename?: string; size_bytes?: number; extension?: string }>("/desktop/pick-file", { method: "POST", body: JSON.stringify({ title: title || "Выберите файл облака точек" }) }),
};"""

new_part = """  pickFileWindows: (title?: string) => request<{ cancelled: boolean; path?: string; filename?: string; size_bytes?: number; extension?: string }>("/desktop/pick-file", { method: "POST", body: JSON.stringify({ title: title || "Выберите файл облака точек" }) }),

  // Registration & Stitching
  matchCloudsIcp: (sourceCloudId: string, targetCloudId: string, samplePoints = 20000, maxIterations = 30) =>
    request<{
      rotation: number[][];
      translation: number[];
      matrix_4x4: number[][];
      rmse_mm: number;
      iterations: number;
      converged: boolean;
    }>("/registration/match", {
      method: "POST",
      body: JSON.stringify({
        source_cloud_id: sourceCloudId,
        target_cloud_id: targetCloudId,
        sample_points: samplePoints,
        max_iterations: maxIterations,
      }),
    }),
  exportStitchedPly: (projectName: string, stations: any[]) =>
    request<{ status: string; output_path: string; size_bytes: number }>("/registration/export-ply", {
      method: "POST",
      body: JSON.stringify({ project_name: projectName, stations }),
    }),
  exportRecapProject: (projectName: string, stations: any[]) =>
    request<{ status: string; output_path: string; stations_count: number }>("/registration/export-recap", {
      method: "POST",
      body: JSON.stringify({ project_name: projectName, stations }),
    }),
};"""

if "pickFileWindows:" in content:
    # Find the end of pickFileWindows and replace
    lines = content.splitlines()
    for idx, line in enumerate(lines):
        if "pickFileWindows:" in line and "};" in lines[idx+1]:
            lines[idx] = """  pickFileWindows: (title?: string) => request<{ cancelled: boolean; path?: string; filename?: string; size_bytes?: number; extension?: string }>("/desktop/pick-file", { method: "POST", body: JSON.stringify({ title: title || "Выберите файл облака точек" }) }),

  // Registration & Stitching
  matchCloudsIcp: (sourceCloudId: string, targetCloudId: string, samplePoints = 20000, maxIterations = 30) =>
    request<{
      rotation: number[][];
      translation: number[];
      matrix_4x4: number[][];
      rmse_mm: number;
      iterations: number;
      converged: boolean;
    }>("/registration/match", {
      method: "POST",
      body: JSON.stringify({
        source_cloud_id: sourceCloudId,
        target_cloud_id: targetCloudId,
        sample_points: samplePoints,
        max_iterations: maxIterations,
      }),
    }),
  exportStitchedPly: (projectName: string, stations: any[]) =>
    request<{ status: string; output_path: string; size_bytes: number }>("/registration/export-ply", {
      method: "POST",
      body: JSON.stringify({ project_name: projectName, stations }),
    }),
  exportRecapProject: (projectName: string, stations: any[]) =>
    request<{ status: string; output_path: string; stations_count: number }>("/registration/export-recap", {
      method: "POST",
      body: JSON.stringify({ project_name: projectName, stations }),
    }),"""
            break
    p.write_text("\n".join(lines), encoding="utf-8")
    print("Added registration API calls to api.ts!")
else:
    print("pickFileWindows not found!")
