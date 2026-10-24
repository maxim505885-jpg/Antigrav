# SCAN Studio design QA

The visual reference is the SCAN Studio screenshot supplied by the user on October 24, 2026. The implementation uses its graphite surfaces, orange highlights, top command ribbon, split RGB/point-cloud viewers, and bottom live status strip while keeping the existing working review tools.

## Acceptance checked

- Production frontend build completed: Vite transformed 1,977 modules and emitted the app, vendor, and Three.js bundles.
- Frontend tests and TypeScript build completed successfully.
- Live browser at `http://127.0.0.1:5174/` loaded the registered FARO `1.rcs` project, its 40,000,000-point stored sample, and 1,482 live candidates.
- API health and project listing both returned HTTP 200 (`/api/v1/health`, `/api/v1/projects`).
- Toolbar exposes project creation, scan import, save view, fit/top camera, 3D measurement, limit box, recognition, column DXF, crane-girder DXF, and IFC actions. Project creation and upload call the API; view settings persist; exports use existing API endpoints.
- Save view, measurement toggle, and panorama navigation were exercised. Panorama navigation reports that no linked 360-degree images exist instead of showing fabricated imagery.
- Browser console contained zero errors and zero warnings after reload.
- Final viewport capture: [`../screenshots/scan-studio-final.png`](../screenshots/scan-studio-final.png). Same-size reference comparison: [`../screenshots/scan-studio-design-comparison.png`](../screenshots/scan-studio-design-comparison.png).

The viewer displays the real registered point cloud rather than the reference screenshot's illustrative factory photograph. Current live point data is sampled, so the status strip reports the sample count and original source count separately. Registration RMSE and engineering tolerance remain explicitly unknown.

Stage 3 remains open: 60 FPS navigation acceptance on the target workstation and representative full cloud has not been measured. This UI/design block does not close any of the 12 roadmap stages.
