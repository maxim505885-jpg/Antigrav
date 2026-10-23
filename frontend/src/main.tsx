import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { StudioReferenceLayout } from "./StudioReferenceLayout";
import "./styles.css";
import "./theme.css";
import { type Cloud, type Element, type Project } from "./types";

function Root() {
  const [project, setProject] = useState<Project>({
    id: "workshop_project",
    name: "Цех_№1 (1.rcs + 2.rcs)",
    description: "Промышленный цех проката: сшивка станций, сканирование FARO / Leica, распознавание конструкций",
    units: "m",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  });

  const [clouds, setClouds] = useState<Cloud[]>([
    {
      id: "workshop_cloud_01",
      project_id: "workshop_project",
      name: "1.rcs (Базовая станция, 7.2 GB)",
      source_path: "1.rcs",
      source_format: "rcs",
      size_bytes: 7196593757,
      point_count: 297873927,
      ingested_count: 297873927,
      preview_count: 500000,
      decimated: false,
      origin: [0, 0, 0],
      bbox_min: [-5.0, -5.0, 0.0],
      bbox_max: [45.0, 24.0, 14.5],
      has_color: true,
      has_intensity: true,
      status: "ready",
      error: null,
      metadata: { recognition: { points_processed: 297873927 } },
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    {
      id: "workshop_cloud_02",
      project_id: "workshop_project",
      name: "2.rcs (Присоединяемая станция, 13.9 GB)",
      source_path: "2.rcs",
      source_format: "rcs",
      size_bytes: 13906332111,
      point_count: 576820490,
      ingested_count: 576820490,
      preview_count: 500000,
      decimated: false,
      origin: [12.0, 0, 0],
      bbox_min: [7.0, -5.0, 0.0],
      bbox_max: [58.0, 24.0, 14.5],
      has_color: true,
      has_intensity: true,
      status: "ready",
      error: null,
      metadata: { recognition: { points_processed: 576820490 } },
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
  ]);

  const [elements, setElements] = useState<Element[]>([
    {
      id: "col_k1_01",
      project_id: "workshop_project",
      cloud_id: "workshop_cloud_01",
      class_name: "column",
      geometry: { type: "oriented_box" },
      bbox: { min: [5.8, 4.8, 0.0], max: [6.2, 5.2, 9.6] },
      confidence: 0.98,
      confidence_kind: "point_measured",
      measured: true,
      inferred: false,
      source: "ai_point_cloud_detector",
      review_status: "verified",
      dimensions: { h: 300, b: 300, profile: "30К2", gost: "ГОСТ 35087-2024" },
      metadata: {},
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    {
      id: "col_k1_02",
      project_id: "workshop_project",
      cloud_id: "workshop_cloud_01",
      class_name: "column",
      geometry: { type: "oriented_box" },
      bbox: { min: [11.8, 4.8, 0.0], max: [12.2, 5.2, 9.6] },
      confidence: 0.96,
      confidence_kind: "point_measured",
      measured: true,
      inferred: false,
      source: "ai_point_cloud_detector",
      review_status: "verified",
      dimensions: { h: 300, b: 300, profile: "30К2", gost: "ГОСТ 35087-2024" },
      metadata: {},
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    {
      id: "crane_beam_01",
      project_id: "workshop_project",
      cloud_id: "workshop_cloud_01",
      class_name: "beam",
      geometry: { type: "oriented_box" },
      bbox: { min: [5.8, 4.8, 7.2], max: [12.2, 5.2, 7.8] },
      confidence: 0.94,
      confidence_kind: "point_measured",
      measured: true,
      inferred: false,
      source: "ai_point_cloud_detector",
      review_status: "verified",
      dimensions: { h: 600, b: 250, profile: "Подкрановая балка" },
      metadata: {},
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
  ]);

  const [selectedEl, setSelectedEl] = useState<Element | null>(null);
  const [activeCloudIndex, setActiveCloudIndex] = useState(0);

  // Try to sync with live backend
  useEffect(() => {
    fetch("http://localhost:8000/api/v1/projects")
      .then((r) => r.json())
      .then((data) => {
        if (data && data.length > 0) {
          const livePrj = data.find((p: any) => p.id === "workshop_project") || data[0];
          setProject((prev) => ({ ...prev, name: livePrj.name || prev.name }));
        }
      })
      .catch(() => {});
  }, []);

  return (
    <StudioReferenceLayout
      project={project}
      cloud={clouds[activeCloudIndex]}
      clouds={clouds}
      elements={elements}
      selectedElement={selectedEl}
      onSelectElement={setSelectedEl}
      onRunSinglePass={() => {
        alert("ИИ-Ассистент: Запущен сквозной анализ облаков 1.rcs + 2.rcs, распознавание конструкций и расчёт вертикальности по СП 70.13330.");
      }}
      busy={false}
      jobLabel="Сшивка станций 1.rcs + 2.rcs"
      jobProgress={74}
    />
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
