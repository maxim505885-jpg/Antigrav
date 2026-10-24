import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { StudioReferenceLayout } from "./StudioReferenceLayout";
import "./styles.css";
import "./theme.css";
import { api, waitForJob } from "./api";
import { type Cloud, type Element, type Project } from "./types";

function Root() {
  const [preferredProjectId] = useState(() => window.localStorage.getItem("scan.selectedProjectId") || undefined);
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [clouds, setClouds] = useState<Cloud[]>([]);
  const [elements, setElements] = useState<Element[]>([]);
  const [selectedEl, setSelectedEl] = useState<Element | null>(null);
  const [busy, setBusy] = useState(false);
  const [jobLabel, setJobLabel] = useState<string | null>(null);
  const [jobProgress, setJobProgress] = useState<number | null>(null);

  // Load live data from local API backend
  const loadData = async (preferredCloudId?: string, preferredProjectId?: string): Promise<number> => {
    try {
      const projectsList = await api.listProjects();
      if (!projectsList || projectsList.length === 0) return 0;

      setProjects(projectsList);
      // Keep the requested/current project; use the workshop as the initial default.
      const prj = projectsList.find((p) => p.id === (preferredProjectId || project?.id))
        || projectsList.find((p) => p.id === "workshop_project")
        || projectsList[0];
      setProject(prj);

      // Load clouds for project
      const cloudList = await api.listClouds(prj.id);
      setClouds(cloudList);

      // Load elements for ready clouds
      const readyCloud = cloudList.find((c) => c.id === preferredCloudId && c.status === "ready")
        || cloudList.find((c) => c.status === "ready" && c.id === "workshop_cloud")
        || cloudList.find((c) => c.status === "ready");
      if (readyCloud) {
        const elList = await api.elements(readyCloud.id);
        setElements(elList);
        return elList.length;
      }
      setElements([]);
      return 0;
    } catch (err) {
      console.warn("Could not sync with local API, running in standalone mode:", err);
      return 0;
    }
  };

  useEffect(() => {
    void loadData(undefined, preferredProjectId);
  }, []);

  const handleRunSinglePass = async (cloudId: string | null) => {
    const target = clouds.find((item) => item.id === cloudId);
    if (!target) {
      setJobLabel("Выберите облако проекта для распознавания");
      return;
    }
    if (target.status !== "ready") {
      setJobLabel(`Облако «${target.name}» ещё не готово к распознаванию`);
      return;
    }
    setBusy(true);
    setJobLabel("Распознавание конструкций");
    setJobProgress(0);
    try {
      const job = await api.recognize(target.id);
      const finished = await waitForJob(job.id, (update) => {
        setJobProgress(update.progress);
        setJobLabel(update.message || "Распознавание конструкций");
      });
      if (finished.status !== "succeeded") {
        throw new Error(finished.error || finished.message || `Задание завершилось со статусом ${finished.status}`);
      }
      const candidateCount = await loadData(target.id);
      setJobLabel(`Распознавание завершено · ${candidateCount} кандидатов`);
      setJobProgress(null);
    } catch (err) {
      setJobLabel(`Ошибка распознавания: ${err instanceof Error ? err.message : String(err)}`);
      setJobProgress(null);
    } finally {
      setBusy(false);
    }
  };

  const handleCloudChange = async (cloudId: string) => {
    setSelectedEl(null);
    const selectedCloud = clouds.find((item) => item.id === cloudId);
    if (!selectedCloud || selectedCloud.status !== "ready") {
      setElements([]);
      return;
    }
    try {
      setElements(await api.elements(cloudId));
    } catch (err) {
      setElements([]);
      setJobLabel(`Не удалось загрузить элементы облака: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleProjectChange = async (projectId: string) => {
    window.localStorage.setItem("scan.selectedProjectId", projectId);
    setSelectedEl(null);
    setElements([]);
    setClouds([]);
    setJobLabel("Загрузка проекта");
    const candidateCount = await loadData(undefined, projectId);
    setJobLabel(`Проект загружен · ${candidateCount} кандидатов`);
  };

  const primaryCloud = clouds.find((c) => c.id === "workshop_cloud") || clouds[0] || null;

  return (
    <StudioReferenceLayout
      projects={projects}
      project={project}
      cloud={primaryCloud}
      clouds={clouds}
      elements={elements}
      selectedElement={selectedEl}
      onSelectElement={setSelectedEl}
      onRunSinglePass={(cloudId) => void handleRunSinglePass(cloudId)}
      onCloudChange={(cloudId) => void handleCloudChange(cloudId)}
      onProjectChange={(projectId) => void handleProjectChange(projectId)}
      busy={busy}
      jobLabel={jobLabel}
      jobProgress={jobProgress}
    />
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
