import React, { useEffect, useRef, useState } from "react";
import ReactDOM from "react-dom/client";
import { StudioReferenceLayout } from "./StudioReferenceLayout";
import "./styles.css";
import "./theme.css";
import { api, waitForJob } from "./api";
import { type Cloud, type Element, type Project } from "./types";
import { selectInitialProject } from "./projectSelection";

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
  const [jobs, setJobs] = useState<import("./types").Job[]>([]);
  const [activeCloudId, setActiveCloudId] = useState<string | undefined>();
  const [selectedEl, setSelectedEl] = useState<Element | null>(null);
  const [busy, setBusy] = useState(false);
  const [dataLoading, setDataLoading] = useState(true);
  const [jobLabel, setJobLabel] = useState<string | null>(null);
  const [jobProgress, setJobProgress] = useState<number | null>(null);
  const [activeImportJobId, setActiveImportJobId] = useState<string | null>(null);
  const [batchImportCounts, setBatchImportCounts] = useState<{
    total: number;
    ready: number;
    processing: number;
    failed: number;
    cancelled: number;
  } | null>(null);
  const attachedBatchJobs = useRef(new Set<string>());

  // Load live data from local API backend
  const loadData = async (preferredCloudId?: string, preferredProjectId?: string): Promise<number> => {
    setDataLoading(true);
    try {
      const projectsList = await api.listProjects();
      if (!projectsList || projectsList.length === 0) return 0;

      setProjects(projectsList);
      // Keep the requested/current project; fresh profiles open the most populated project.
      const prj = selectInitialProject(projectsList, preferredProjectId || project?.id)!;
      setProject(prj);

      const projectJobs = await api.projectJobs(prj.id);
      setJobs(projectJobs);

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
      const detail = err instanceof Error ? err.message : String(err);
      setJobLabel("Не удалось загрузить данные из API: " + detail);
      return -1;
    } finally {
      setDataLoading(false);
    }
  };

  useEffect(() => {
    void loadData(preferredCloudId, preferredProjectId);
  }, []);

  useEffect(() => {
    if (!project) return;
    const activeBatch = jobs.find((job) => job.type === "rcp_batch_ingest" && ["queued", "running"].includes(job.status));
    if (!activeBatch || attachedBatchJobs.current.has(activeBatch.id)) return;
    attachedBatchJobs.current.add(activeBatch.id);
    setActiveImportJobId(activeBatch.id);
    setBusy(true);

    const countsForJob = (items: Cloud[], message: string) => {
      const stationName = message.match(/Станция\s+\d+\/\d+:\s*(.*?)\s+—/i)?.[1]?.trim();
      const currentStation = stationName
        ? items.find((item) => item.metadata?.recap_project?.selected_node?.name === stationName)
        : undefined;
      const projectSha = currentStation?.metadata?.recap_project?.project_sha256;
      const stations = projectSha
        ? items.filter((item) => item.metadata?.recap_project?.project_sha256 === projectSha)
        : [];
      if (!stations.length) return null;
      const totalFromMessage = Number(message.match(/Станция\s+\d+\/(\d+)/i)?.[1]);
      return {
        total: totalFromMessage > 0 ? totalFromMessage : stations.length,
        ready: stations.filter((item) => item.status === "ready").length,
        processing: stations.filter((item) => item.status === "processing").length,
        failed: stations.filter((item) => item.status === "failed").length,
        cancelled: stations.filter((item) => item.status === "cancelled").length,
      };
    };

    let lastCloudStatusPoll = 0;
    let cloudStatusPollInFlight = false;
    let finished = false;
    setJobLabel(activeBatch.message ? `Импорт RCP: ${activeBatch.message}` : "Импорт станций RCP");
    setJobProgress(activeBatch.progress);
    const initialCounts = countsForJob(clouds, activeBatch.message || "");
    if (initialCounts) setBatchImportCounts(initialCounts);

    void waitForJob(activeBatch.id, (update) => {
      setJobProgress(update.progress);
      setJobLabel(update.message ? `Импорт RCP: ${update.message}` : "Импорт станций RCP");
      const now = Date.now();
      if (!finished && !cloudStatusPollInFlight && now - lastCloudStatusPoll >= 10_000) {
        lastCloudStatusPoll = now;
        cloudStatusPollInFlight = true;
        void api.listClouds(project.id)
          .then((list) => {
            if (finished) return;
            setClouds(list);
            const counts = countsForJob(list, update.message || activeBatch.message || "");
            if (counts) setBatchImportCounts(counts);
          })
          .catch(() => undefined)
          .finally(() => { cloudStatusPollInFlight = false; });
      }
    }, 24 * 60 * 60 * 1000)
      .then(async (job) => {
        finished = true;
        await loadData(undefined, project.id);
        if (job.status === "failed") setJobLabel(job.error || "Импорт станций RCP завершился ошибкой");
      })
      .catch((error) => {
        finished = true;
        setJobLabel(`Потеряно наблюдение за импортом RCP: ${error instanceof Error ? error.message : String(error)}`);
      })
      .finally(() => {
        setActiveImportJobId(null);
        setBatchImportCounts(null);
        setBusy(false);
        setJobProgress(null);
        attachedBatchJobs.current.delete(activeBatch.id);
      });
  }, [jobs, project?.id, clouds]);

  const handleResumeRcpBatch = async (jobId: string) => {
    if (!project) throw new Error("Сначала выберите проект.");
    const resumed = await api.resumeRcpBatchJob(project.id, jobId);
    setJobs((current) => current.map((job) => job.id === resumed.id ? resumed : job));
  };

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
    const previousProjectId = project?.id;
    window.localStorage.setItem("scan.selectedProjectId", projectId);
    setJobLabel("Загрузка проекта");
    const candidateCount = await loadData(undefined, projectId);
    if (candidateCount < 0) {
      if (previousProjectId) window.localStorage.setItem("scan.selectedProjectId", previousProjectId);
      else window.localStorage.removeItem("scan.selectedProjectId");
      return;
    }
    setSelectedEl(null);
    setJobLabel(`Проект загружен · ${candidateCount} кандидатов`);
  };

  const handleCreateProject = async (name: string) => {
    const created = await api.createProject(name);
    setActiveCloudId(undefined);
    await loadData(undefined, created.id);
    setJobLabel(`Проект «${created.name}» создан`);
  };

  const handleUploadScan = async (file: File, maxPoints?: number) => {
    if (!project) throw new Error("Сначала выберите проект.");
    setBusy(true);
    setJobLabel(`Загрузка «${file.name}»`);
    setJobProgress(0);
    try {
      const incoming = await api.uploadCloud(project.id, file, undefined, maxPoints);
      setActiveCloudId(incoming.id);
      if (!incoming.import_job_id) throw new Error("API не создал фоновое задание импорта.");
      setActiveImportJobId(incoming.import_job_id);
      const job = await waitForJob(incoming.import_job_id, (update) => {
        setJobProgress(update.progress);
        setJobLabel(update.message || "Обработка облака точек");
      }, 60 * 60 * 1000);
      const ready = await api.getCloud(incoming.id);
      if (job.status !== "succeeded" || ready.status !== "ready") {
        throw new Error(job.error || ready.error || `Импорт завершился со статусом ${ready.status}`);
      }
      await loadData(ready.id, project.id);
      setActiveCloudId(ready.id);
      setJobLabel(`Скан готов · ${ready.name}`);
      setJobProgress(null);
    } finally {
      setActiveImportJobId(null);
      setBusy(false);
      setJobProgress(null);
    }
  };

  const handleImportPath = async (path: string, maxPoints?: number) => {
    if (!project) throw new Error("Сначала выберите проект.");
    setBusy(true);
    setJobLabel(`Импорт ${path.split(/[\\/]/).pop() || path}`);
    setJobProgress(0.02);
    try {
      if (path.trim().toLowerCase().endsWith(".rcp")) {
        const batch = await api.importRcpPath(project.id, path.trim(), undefined, maxPoints);
        setActiveImportJobId(batch.import_job_id);
        const stationIds = new Set(batch.stations.map((station) => station.cloud.id));
        const updateBatchCounts = (items: Cloud[]) => {
          const imported = items.filter((item) => stationIds.has(item.id));
          setBatchImportCounts({
            total: batch.node_count,
            ready: imported.filter((item) => item.status === "ready").length,
            processing: imported.filter((item) => item.status === "processing").length,
            failed: imported.filter((item) => item.status === "failed").length,
            cancelled: imported.filter((item) => item.status === "cancelled").length,
          });
        };
        updateBatchCounts(batch.stations.map((station) => station.cloud));
        let lastCloudStatusPoll = 0;
        let cloudStatusPollInFlight = false;
        let finished = false;
        const job = await waitForJob(batch.import_job_id, (update) => {
          setJobProgress(update.progress || 0.03);
          setJobLabel(update.message ? `Импорт RCP: ${update.message}` : "Импорт станций RCP");
          const now = Date.now();
          if (!finished && !cloudStatusPollInFlight && now - lastCloudStatusPoll >= 10_000) {
            lastCloudStatusPoll = now;
            cloudStatusPollInFlight = true;
            void api.listClouds(project.id)
              .then((list) => {
                if (finished) return;
                const imported = list.filter((item) => stationIds.has(item.id));
                updateBatchCounts(imported);
                setClouds([...imported, ...list.filter((item) => !stationIds.has(item.id))]);
              })
              .catch(() => undefined)
              .finally(() => { cloudStatusPollInFlight = false; });
          }
        }, 30 * 60 * 1000);
        finished = true;
        await loadData(undefined, project.id);
        if (job.status === "cancelled") throw new Error("Импорт станций RCP отменён.");
        if (job.status === "failed") throw new Error(job.error || "Импорт станций RCP завершился ошибкой.");
        if (job.result?.failed_count) {
          throw new Error(`Готово ${job.result.ready_count}/${job.result.node_count} станций RCP.`);
        }
        setJobLabel(`Готово · импортировано станций: ${batch.node_count}`);
        return;
      }
      const incoming = await api.importPath(project.id, path.trim(), undefined, maxPoints);
      setActiveCloudId(incoming.id);
      if (!incoming.import_job_id) throw new Error("API не создал фоновое задание импорта.");
      setActiveImportJobId(incoming.import_job_id);
      const job = await waitForJob(incoming.import_job_id, (update) => {
        setJobProgress(update.progress);
        setJobLabel(update.message || "Импорт облака");
      }, 60 * 60 * 1000);
      const ready = await api.getCloud(incoming.id);
      if (job.status !== "succeeded" || ready.status !== "ready") {
        throw new Error(job.error || ready.error || `Импорт завершился со статусом ${ready.status}`);
      }
      await loadData(ready.id, project.id);
      setActiveCloudId(ready.id);
      setJobLabel(`Готово · ${ready.name} · ${ready.ingested_count.toLocaleString("ru-RU")} точек`);
    } finally {
      setActiveImportJobId(null);
      setBatchImportCounts(null);
      setBusy(false);
      setJobProgress(null);
    }
  };

  const handleCancelImport = async () => {
    if (!activeImportJobId) return;
    const result = await api.cancelJob(activeImportJobId);
    setJobLabel(result.cancel_requested ? "Запрошена отмена импорта; ожидаю безопасную границу чанка…" : "Импорт уже завершился; отменять нечего.");
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
      jobs={jobs}
      dataLoading={dataLoading}
      selectedElement={selectedEl}
      onSelectElement={setSelectedEl}
      onRunSinglePass={(cloudId) => void handleRunSinglePass(cloudId)}
      onCloudChange={(cloudId) => void handleCloudChange(cloudId)}
      onProjectChange={(projectId) => void handleProjectChange(projectId)}
      onCreateProject={handleCreateProject}
      onUploadScan={handleUploadScan}
      onImportPath={handleImportPath}
      onCancelImport={handleCancelImport}
      onResumeRcpBatch={handleResumeRcpBatch}
      canCancelImport={activeImportJobId !== null}
      busy={busy}
      jobLabel={jobLabel}
      jobProgress={jobProgress}
      batchImportCounts={batchImportCounts}
    />
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
