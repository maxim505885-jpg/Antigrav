import React from "react";
import ReactDOM from "react-dom/client";
import { StudioReferenceLayout } from "./StudioReferenceLayout";
import "./styles.css";
import "./theme.css";

const demoProject = {
  id: "proj_workshop_01",
  name: "Завод_Цех_1",
  description: "Промышленный цех по производству металлоконструкций",
  units: "m",
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

const demoCloud = {
  id: "cloud_workshop_01",
  project_id: "proj_workshop_01",
  name: "1.rcs + FARO Focus",
  source_path: "1.rcs",
  source_format: "rcs",
  size_bytes: 6710886400,
  point_count: 32500000,
  ingested_count: 32500000,
  preview_count: 500000,
  decimated: false,
  origin: [0, 0, 0] as [number, number, number],
  bbox_min: [-2.0, -2.0, 0.0] as [number, number, number],
  bbox_max: [45.0, 20.0, 12.0] as [number, number, number],
  has_color: true,
  has_intensity: true,
  status: "ready" as const,
  error: null,
  metadata: { recognition: { points_processed: 32500000 } },
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

function Root() {
  const [selectedEl, setSelectedEl] = React.useState<any>(null);

  return (
    <StudioReferenceLayout
      project={demoProject}
      cloud={demoCloud}
      clouds={[demoCloud]}
      elements={[]}
      selectedElement={selectedEl}
      onSelectElement={setSelectedEl}
      onRunSinglePass={() => alert("ИИ-обработка запущена (RTX 4090: сегментация, детекция и СПДС)")}
      busy={false}
      jobLabel="Регистрация и сшивка"
      jobProgress={68}
    />
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
