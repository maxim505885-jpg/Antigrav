import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { StudioReferenceLayout } from "./StudioReferenceLayout";
import "./styles.css";
import "./theme.css";
import { api, waitForCloud, waitForJob } from "./api";
import { type Cloud, type Element, type Project } from "./types";

function Root() {
  const [preferredProjectId] = useState(() => window.localStorage.getItem("scan.selectedProjectId") || undefined);
  const [preferredCloudId] = useState(() => {
    try {
      const stored = window.localStorage.getItem("scan.studioView");
      const cloudId = stored ? JSON.parse(stored)?.cloudId : undefined;
      return typeof cloudId === "string" ? cloudId : undefined;
    } catch {
      return undefined;
    }
  });
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [clouds, setClouds] = useState<Cloud[]>([]);
  const [elements, setElements] = useState<Element[]>([]);
  const [activeCloudId, setActiveCloudId] = useState<string | undefined>();
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
        setActiveCloudId(readyCloud.id);
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
    void loadData(preferredCloudId, preferredProjectId);
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
    setActiveCloudId(cloudId);
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

  const handleCreateProject = async (name: string) => {
    const created = await api.createProject(name);
    setActiveCloudId(undefined);
    await loadData(undefined, created.id);
    setJobLabel(`Проект «${created.name}» создан`);
  };

  const handleUploadScan = async (file: File) => {
    if (!project) throw new Error("Сначала выберите проект.");
    setBusy(true);
    setJobLabel(`Загрузка «${file.name}»`);
    setJobProgress(0);
    try {
      const incoming = await api.uploadCloud(project.id, file);
      setActiveCloudId(incoming.id);
      setJobLabel("Обработка облака точек");
      setJobProgress(0.05);
      const ready = await waitForCloud(incoming.id, (update) => {
        setJobProgress(update.status === "processing" ? 0.5 : 0.9);
        setJobLabel(update.status === "processing" ? "Обработка облака точек" : update.status);
      });
      if (ready.status !== "ready") throw new Error(ready.error || `Импорт завершился со статусом ${ready.status}`);
      await loadData(ready.id, project.id);
      setActiveCloudId(ready.id);
      setJobLabel(`Скан готов · ${ready.name}`);
      setJobProgress(null);
    } finally {
      setBusy(false);
      setJobProgress(null);
    }
  };

  const primaryCloud = clouds.find((c) => c.id === activeCloudId)
    || clouds.find((c) => c.id === "workshop_cloud")
    || clouds[0]
    || null;

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
      onCreateProject={handleCreateProject}
      onUploadScan={handleUploadScan}
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
