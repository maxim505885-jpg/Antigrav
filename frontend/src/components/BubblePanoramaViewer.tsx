import React, { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import {
  api,
  type PanoramaPick,
  type PanoramaMeasureResult,
  type StationPanoramaSummary,
  waitForJob,
} from "../api";

/**
 * 360° station viewer.
 *
 * The image is whatever the backend really has for the station: an uploaded
 * equirectangular photograph, or a panorama rendered from the stored points.
 * Distance is measured by the backend through the cloud depth map, so a value
 * is shown only when the points support it; otherwise the reason is shown
 * instead of an invented number.
 */

interface Props {
  cloudId?: string | null;
  stationId?: string | null;
  onClose?: () => void;
  onPointMeasure?: (point: [number, number, number]) => void;
}

const PANEL_BG = "rgba(15, 23, 42, 0.9)";
const BORDER = "#303943";

function describeError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  try {
    const parsed = JSON.parse(message);
    const detail = parsed?.detail ?? parsed;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object") {
      return [detail.summary, detail.message, detail.reason]
        .filter((part) => typeof part === "string" && part.length > 0)
        .join(" ");
    }
  } catch {
    /* not JSON: fall through to the raw message */
  }
  return message;
}

export const BubblePanoramaViewer: React.FC<Props> = ({
  cloudId,
  stationId,
  onClose,
  onPointMeasure,
}) => {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const meshRef = useRef<THREE.Mesh | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);

  const [stations, setStations] = useState<StationPanoramaSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(stationId ?? null);
  const [source, setSource] = useState<"auto" | "photo" | "cloud">("auto");
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [loadingCatalog, setLoadingCatalog] = useState(false);
  const [imageError, setImageError] = useState<string | null>(null);
  const [imageVersion, setImageVersion] = useState(0);
  const [renderProgress, setRenderProgress] = useState<{ progress: number; message: string } | null>(null);
  const [readyPanoramaKey, setReadyPanoramaKey] = useState<string | null>(null);

  const [measureMode, setMeasureMode] = useState(false);
  const [picks, setPicks] = useState<Array<{ u: number; v: number; pick: PanoramaPick | null }>>([]);
  const [measurement, setMeasurement] = useState<PanoramaMeasureResult | null>(null);
  const [measureError, setMeasureError] = useState<string | null>(null);
  const [busyMeasure, setBusyMeasure] = useState(false);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [yawOffset, setYawOffset] = useState("0");

  const picksRef = useRef<Array<{ u: number; v: number; pick: PanoramaPick | null }>>([]);

  useEffect(() => {
    picksRef.current = picks;
  }, [picks]);

  const current = stations.find((entry) => entry.station_id === selected) ?? null;
  const photoAvailable = Boolean(current?.has_photo);
  const effectiveSource = source === "photo" && !photoAvailable ? "cloud" : source;
  const needsPointCloudRender = effectiveSource === "cloud" || (effectiveSource === "auto" && !photoAvailable);
  const panoramaKey = cloudId && current ? `${cloudId}:${current.station_id}` : null;
  const panoramaReady = !needsPointCloudRender || Boolean(panoramaKey && readyPanoramaKey === panoramaKey);

  const imageUrl =
    cloudId && current && panoramaReady
      ? api.stationPanoramaUrl(cloudId, current.station_id, {
          source: effectiveSource,
          version: String(
            (effectiveSource === "photo" ? current.photo?.uploaded_at : current.cloud_panorama?.rendered_at) ??
              imageVersion,
          ),
        })
      : undefined;

  const loadStations = useCallback(async () => {
    if (!cloudId) {
      setStations([]);
      return;
    }
    setLoadingCatalog(true);
    setCatalogError(null);
    try {
      const response = await api.listStations(cloudId);
      setStations(response.stations);
      setSelected((previous) => {
        if (previous && response.stations.some((entry) => entry.station_id === previous)) return previous;
        return response.stations[0]?.station_id ?? null;
      });
    } catch (error) {
      setStations([]);
      setCatalogError(describeError(error));
    } finally {
      setLoadingCatalog(false);
    }
  }, [cloudId]);

  useEffect(() => {
    void loadStations();
  }, [loadStations]);

  useEffect(() => {
    if (!cloudId || !current || !panoramaKey || !needsPointCloudRender) {
      setRenderProgress(null);
      return;
    }
    let active = true;
    setReadyPanoramaKey(null);
    setImageError(null);
    setRenderProgress({ progress: 0.01, message: "Проверяю готовность панорамы…" });
    void (async () => {
      try {
        const response = await api.ensureStationPanorama(cloudId, current.station_id);
        if (response.status === "queued") {
          const finished = await waitForJob(
            response.job.id,
            (job) => {
              if (active) setRenderProgress({ progress: job.progress, message: job.message || "Строю панораму…" });
            },
            30 * 60 * 1000,
          );
          if (finished.status !== "succeeded") {
            throw new Error(finished.error || finished.message || `Построение завершилось со статусом ${finished.status}`);
          }
        }
        await loadStations();
        if (active) {
          setImageVersion((version) => version + 1);
          setReadyPanoramaKey(panoramaKey);
        }
      } catch (error) {
        if (active) setImageError(`Не удалось построить панораму: ${describeError(error)}`);
      } finally {
        if (active) setRenderProgress(null);
      }
    })();
    return () => {
      active = false;
    };
  }, [cloudId, current?.station_id, effectiveSource, loadStations, needsPointCloudRender, panoramaKey]);

  useEffect(() => {
    if (stationId) setSelected(stationId);
  }, [stationId]);

  useEffect(() => {
    picksRef.current = [];
    setPicks([]);
    setMeasurement(null);
    setMeasureError(null);
    setImageError(null);
    setUploadError(null);
  }, [selected, effectiveSource]);

  // Keep the click handler current without rebuilding the renderer.
  const stateRef = useRef({ measureMode, cloudId, selected, imageUrl, busyMeasure });
  useEffect(() => {
    stateRef.current = { measureMode, cloudId, selected, imageUrl, busyMeasure };
  }, [measureMode, cloudId, selected, imageUrl, busyMeasure]);

  const handlePick = useCallback(
    async (uv: { u: number; v: number }) => {
      const { measureMode: mode, cloudId: activeCloud, selected: activeStation, imageUrl: activeImage } =
        stateRef.current;
      if (!mode || !activeCloud || !activeStation || !activeImage) return;
      setMeasureError(null);
      setBusyMeasure(true);
      try {
        const pick = await api.pickOnStation(activeCloud, activeStation, uv);
        const previous = picksRef.current;
        const a = previous[previous.length - 1];
        const next = [...(a ? [a] : []), { ...uv, pick }];
        picksRef.current = next;
        setPicks(next);
        if (next.length < 2) {
          setBusyMeasure(false);
          return;
        }
        try {
          const result = await api.measureOnStation(
            activeCloud,
            activeStation,
            { u: next[0].u, v: next[0].v },
            { u: next[1].u, v: next[1].v },
          );
          setMeasurement(result);
          setMeasureError(null);
          if (next[1].pick?.point && onPointMeasure) {
            onPointMeasure(next[1].pick.point as [number, number, number]);
          }
        } catch (error) {
          setMeasurement(null);
          setMeasureError(describeError(error));
        }
      } catch (error) {
        setMeasureError(describeError(error));
      } finally {
        setBusyMeasure(false);
      }
    },
    [onPointMeasure],
  );

  // Build the 360 scene whenever the image changes.
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    if (!imageUrl) {
      meshRef.current = null;
      cameraRef.current = null;
      return;
    }

    let width = mount.clientWidth || 800;
    let height = mount.clientHeight || 450;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, width / height, 0.1, 1000);
    camera.position.set(0, 0, 0.1);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height);
    mount.appendChild(renderer.domElement);

    const geometry = new THREE.SphereGeometry(50, 60, 40);
    geometry.scale(-1, 1, 1); // look at the inside of the sphere
    const material = new THREE.MeshBasicMaterial({ color: 0x11151b });
    const sphere = new THREE.Mesh(geometry, material);
    scene.add(sphere);
    meshRef.current = sphere;

    let texture: THREE.Texture | null = null;
    const loader = new THREE.TextureLoader();
    loader.load(
      imageUrl,
      (loaded) => {
        loaded.colorSpace = THREE.SRGBColorSpace;
        texture = loaded;
        material.map = loaded;
        material.color.set(0xffffff);
        material.needsUpdate = true;
        setImageError(null);
      },
      undefined,
      () => {
        setImageError("Не удалось загрузить изображение станции: сервер вернул ошибку. Проверьте, что облако импортировано.");
      },
    );

    const resize = () => {
      width = mount.clientWidth || width;
      height = mount.clientHeight || height;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(resize);
    observer?.observe(mount);

    let lon = 0;
    let lat = 0;
    let dragStartX = 0;
    let dragStartY = 0;
    let dragStartLon = 0;
    let dragStartLat = 0;
    let dragging = false;
    let moved = 0;

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();

    const onPointerDown = (event: PointerEvent) => {
      if (event.button !== 0) return;
      dragging = true;
      moved = 0;
      dragStartX = event.clientX;
      dragStartY = event.clientY;
      dragStartLon = lon;
      dragStartLat = lat;
      renderer.domElement.setPointerCapture?.(event.pointerId);
    };

    const onPointerMove = (event: PointerEvent) => {
      if (!dragging) return;
      const dx = event.clientX - dragStartX;
      const dy = event.clientY - dragStartY;
      moved = Math.max(moved, Math.abs(dx) + Math.abs(dy));
      lon = dragStartLon - dx * 0.15;
      lat = dragStartLat + dy * 0.15;
    };

    const onPointerUp = (event: PointerEvent) => {
      if (!dragging) return;
      dragging = false;
      renderer.domElement.releasePointerCapture?.(event.pointerId);
      if (moved > 4 || !stateRef.current.measureMode) return;

      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObject(sphere, false)[0];
      if (!hit || !hit.uv) return;
      void handlePick({ u: THREE.MathUtils.clamp(hit.uv.x, 0, 1), v: THREE.MathUtils.clamp(hit.uv.y, 0, 1) });
    };

    const element = renderer.domElement;
    element.addEventListener("pointerdown", onPointerDown);
    element.addEventListener("pointermove", onPointerMove);
    element.addEventListener("pointerup", onPointerUp);

    let animId = 0;
    const animate = () => {
      animId = requestAnimationFrame(animate);
      lat = Math.max(-85, Math.min(85, lat));
      const phi = THREE.MathUtils.degToRad(90 - lat);
      const theta = THREE.MathUtils.degToRad(lon);
      const target = new THREE.Vector3(
        500 * Math.sin(phi) * Math.cos(theta),
        500 * Math.cos(phi),
        500 * Math.sin(phi) * Math.sin(theta),
      );
      camera.lookAt(target);
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      cancelAnimationFrame(animId);
      observer?.disconnect();
      element.removeEventListener("pointerdown", onPointerDown);
      element.removeEventListener("pointermove", onPointerMove);
      element.removeEventListener("pointerup", onPointerUp);
      texture?.dispose();
      geometry.dispose();
      material.dispose();
      renderer.dispose();
      if (mount.contains(element)) mount.removeChild(element);
      meshRef.current = null;
      cameraRef.current = null;
    };
  }, [imageUrl, handlePick]);

  const resetMeasure = () => {
    picksRef.current = [];
    setPicks([]);
    setMeasurement(null);
    setMeasureError(null);
  };

  const uploadPhoto = async (file: File | undefined) => {
    if (!file || !cloudId || !current) return;
    setUploadBusy(true);
    setUploadError(null);
    try {
      const offset = Number(yawOffset);
      await api.uploadStationPhoto(
        cloudId,
        current.station_id,
        file,
        Number.isFinite(offset) ? offset : 0,
      );
      await loadStations();
      setSource("photo");
      setImageVersion((value) => value + 1);
    } catch (error) {
      setUploadError(describeError(error));
    } finally {
      setUploadBusy(false);
    }
  };

  const removePhoto = async () => {
    if (!cloudId || !current) return;
    setUploadBusy(true);
    setUploadError(null);
    try {
      await api.deleteStationPhoto(cloudId, current.station_id);
      await loadStations();
      setSource("cloud");
      setImageVersion((value) => value + 1);
    } catch (error) {
      setUploadError(describeError(error));
    } finally {
      setUploadBusy(false);
    }
  };

  if (!cloudId) {
    return (
      <div className="empty-note">
        Панорамы стоянок появятся здесь после выбора облака: изображение строится из реальных точек либо
        берётся из загруженной эквидистантной фотографии, а замер считается по глубине облака.
      </div>
    );
  }

  return (
    <div>
      {loadingCatalog && <div className="hint">Читаю стоянки облака…</div>}
      {catalogError && (
        <div className="hint" style={{ color: "#FCA5A5" }}>
          Стоянки недоступны: {catalogError}
        </div>
      )}

      {!loadingCatalog && !catalogError && stations.length === 0 && (
        <div className="hint">
          В метаданных этого облака нет стоянок сканера. Панораму можно построить только для облака,
          импортированного с разбивкой по станциям.
        </div>
      )}

      {stations.length > 0 && current && (
        <>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 8 }}>
            <select
              value={current.station_id}
              onChange={(event) => setSelected(event.target.value)}
              style={{ background: "#141418", color: "#F2F4F6", border: `1px solid ${BORDER}`, borderRadius: 4, padding: "6px 8px" }}
            >
              {stations.map((entry) => (
                <option key={entry.station_id} value={entry.station_id}>
                  {entry.name} · {entry.point_count.toLocaleString("ru-RU")} точек
                </option>
              ))}
            </select>
            <button type="button" onClick={() => setSource("auto")} disabled={source === "auto"}>
              Авто
            </button>
            <button type="button" onClick={() => setSource("photo")} disabled={!photoAvailable}>
              Фотопанорама
            </button>
            <button type="button" onClick={() => setSource("cloud")}>
              Из облака
            </button>
            <button
              type="button"
              onClick={() => {
                const next = !measureMode;
                setMeasureMode(next);
                if (!next) resetMeasure();
              }}
              style={{
                background: measureMode ? "#FF812E" : undefined,
                color: measureMode ? "#10151B" : undefined,
                fontWeight: 600,
              }}
            >
              {measureMode ? "📏 Замер включён" : "📏 Включить замер"}
            </button>
            {measureMode && (
              <button type="button" onClick={resetMeasure} disabled={busyMeasure}>
                Сбросить точки
              </button>
            )}
          </div>

          <div style={{ fontSize: 12, color: "#9CA3AF", marginBottom: 6 }}>
            {effectiveSource === "photo" && current.photo
              ? `Фотография ${current.photo.width}×${current.photo.height} px, SHA-256 ${current.photo.sha256.slice(0, 12)}…, смещение по азимуту ${current.photo.yaw_offset_deg}°`
              : current.has_cloud_panorama && current.cloud_panorama
                ? `Панорама из точек: покрытие ${(current.cloud_panorama.coverage * 100).toFixed(1)}%, цвет — ${
                    current.cloud_panorama.color_source === "cloud_rgb" ? "RGB облака" : "шкала высот"
                  }, дальность ${current.cloud_panorama.max_range_m} м`
                : "Панорама из облака строится фоновой задачей; ход выполнения показан здесь."}
            {current.anchor_kind === "measured_station_centroid" &&
              " · точка обзора — измеренный центроид точек стоянки, а не оптический центр сканера."}
          </div>

          <div
            style={{
              position: "relative",
              width: "100%",
              height: 450,
              borderRadius: 8,
              overflow: "hidden",
              border: `1px solid ${BORDER}`,
              background: "#000",
            }}
          >
            <div ref={mountRef} style={{ width: "100%", height: "100%", cursor: measureMode ? "crosshair" : "grab" }} />

            <div
              style={{
                position: "absolute",
                top: 10,
                left: 10,
                zIndex: 10,
                display: "flex",
                gap: 8,
                flexWrap: "wrap",
                maxWidth: "calc(100% - 20px)",
              }}
            >
              <div style={{ background: PANEL_BG, padding: "6px 12px", borderRadius: 4, fontSize: 12, color: "#fff", border: `1px solid ${BORDER}` }}>
                <strong>360° станция:</strong> {current.name} · {current.station_source === "station_row_ranges" ? "разбивка по стоянкам" : "единое облако"}
              </div>
              {measurement && (
                <div
                  style={{
                    background: "#1E252D",
                    color: measurement.reliable === false ? "#FBBF24" : "#49C980",
                    fontWeight: 700,
                    padding: "6px 12px",
                    borderRadius: 4,
                    fontSize: 12,
                    border: `1px solid ${measurement.reliable === false ? "#FBBF24" : "#49C980"}`,
                    maxWidth: 420,
                  }}
                >
                  {(measurement.distance_mm / 1000).toFixed(3)} м ({measurement.distance_mm.toFixed(0)} мм) · точность ±{measurement.precision_mm.toFixed(0)} мм
                  {measurement.reliable === false && measurement.warning && (
                    <div style={{ fontWeight: 400, marginTop: 4, lineHeight: 1.35 }}>{measurement.warning}</div>
                  )}
                </div>
              )}
              {busyMeasure && (
                <div style={{ background: PANEL_BG, color: "#FBBF24", padding: "6px 12px", borderRadius: 4, fontSize: 12, border: `1px solid ${BORDER}` }}>
                  Считаю глубину по облаку…
                </div>
              )}
            </div>

            {measureError && (
              <div
                style={{
                  position: "absolute",
                  bottom: 10,
                  left: 10,
                  right: 10,
                  background: "rgba(127, 29, 29, 0.92)",
                  color: "#FECACA",
                  padding: "8px 12px",
                  borderRadius: 4,
                  fontSize: 12,
                  border: "1px solid #B91C1C",
                }}
              >
                {measureError}
              </div>
            )}

            {imageError && (
              <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "#FCA5A5", fontSize: 13, padding: 24, textAlign: "center" }}>
                {imageError}
              </div>
            )}

            {renderProgress && !imageError && (
              <div role="status" aria-live="polite" style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10, color: "#F2F4F6", background: "rgba(10, 14, 20, 0.88)", padding: 24, textAlign: "center" }}>
                <strong>Готовлю панораму из облака точек</strong>
                <span style={{ color: "#AAB2BB", fontSize: 13 }}>{renderProgress.message}</span>
                <div style={{ width: "min(320px, 80%)", height: 5, borderRadius: 4, background: "#303943", overflow: "hidden" }}>
                  <div style={{ width: `${Math.max(2, Math.min(100, renderProgress.progress * 100))}%`, height: "100%", background: "#F97316", transition: "width 180ms ease" }} />
                </div>
              </div>
            )}

            {onClose && (
              <button
                type="button"
                onClick={onClose}
                style={{ position: "absolute", top: 10, right: 10, zIndex: 10, background: "rgba(239, 68, 68, 0.8)", color: "#fff", border: "none", borderRadius: 4, padding: "4px 8px", cursor: "pointer", fontSize: 12 }}
              >
                Закрыть панораму
              </button>
            )}
          </div>

          {measureMode && (
            <div style={{ fontSize: 12, color: "#9CA3AF", marginTop: 6 }}>
              {picks.length === 0 && "Кликните первую точку на панораме."}
              {picks.length === 1 && "Кликните вторую точку: расстояние считается по глубине облака в обоих направлениях."}
              {picks.length === 1 && picks[0].pick && !picks[0].pick.resolved && (
                <span style={{ color: "#FCA5A5" }}> В первой точке нет точек облака — выберите другое место.</span>
              )}
              {picks.length === 2 && !measurement && !busyMeasure && !measureError && "Пара точек выбрана."}
            </div>
          )}

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 10 }}>
            <label style={{ fontSize: 12, color: "#9CA3AF" }}>
              Фотопанорама 2:1 (PNG/JPEG/WEBP/TIFF), смещение азимута, °:{" "}
              <input
                type="number"
                value={yawOffset}
                step="1"
                min="-360"
                max="360"
                onChange={(event) => setYawOffset(event.target.value)}
                style={{ width: 70, background: "#141418", color: "#F2F4F6", border: `1px solid ${BORDER}`, borderRadius: 4, padding: "4px 6px" }}
              />
            </label>
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp,image/tiff"
              disabled={uploadBusy}
              onChange={(event) => {
                void uploadPhoto(event.target.files?.[0]);
                event.target.value = "";
              }}
            />
            {photoAvailable && (
              <button type="button" onClick={() => void removePhoto()} disabled={uploadBusy}>
                Удалить фото стоянки
              </button>
            )}
            {uploadBusy && <span style={{ fontSize: 12, color: "#FBBF24" }}>Сохраняю изображение…</span>}
          </div>
          {uploadError && (
            <div style={{ fontSize: 12, color: "#FCA5A5", marginTop: 6 }}>{uploadError}</div>
          )}
        </>
      )}
    </div>
  );
};
