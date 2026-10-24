# SCAN Studio design QA

The visual reference is the SCAN Studio screenshot supplied by the user on October 24, 2026. The implementation uses its graphite surfaces, orange highlights, top command ribbon, split RGB/point-cloud viewers, and bottom live status strip while keeping the existing working review tools.

## Acceptance checked

- Narrow-screen check at 375x812: both scenes stack vertically above the bottom dock, the full status summary remains readable, and neither the page nor status strip clips horizontally.

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

Latest visual refinement — 24 October 2026

The compact top bar now leaves the project, live viewer status, inspection drawer, and recognition action clear at both reviewed desktop widths. Color mode controls sit inside each scene so operators change the view where they work; unavailable modes remain disabled with a reason. The on-demand inspector overlays the workspace, keeps review tools accessible, and hides the navigation cube while open. Opening and closing it was exercised in Chromium. Scene 1 mode switching was exercised from RGB to height Z. Browser QA also checked 1670x956 and 1280x800, no document-level horizontal overflow, keyboard-visible focus, reduced-motion support, and a clean console after reload. The UI remains connected to the local API and shows the selected real 1.rcs derived cloud and current candidate list.

Final screenshots: ../screenshots/scan-studio-1670x956-final.png and ../screenshots/scan-studio-1280x800-final.png. The reference image illustrates a photograph and measured deviation surface; the current FARO cloud has no linked panorama or accepted deviation baseline, so the app keeps its actual point data and states those capabilities as unavailable. At the time of this initial visual pass, loading, API-error, and empty-project states had not been triggered; the follow-up finish-gate below covers all three. Stage 3 remains open pending 60 FPS measurement on the target workstation.

Дополнительный finish-gate прогон для состояний интерфейса, 24 октября 2026: без изменения сервера проверены задержанная загрузка проекта, пустой Test Proj и искусственный сетевой сбой внутри текущей вкладки; после сбоя сеть восстановлена и открыт исходный FARO-проект. Ошибка доступна как role=alert/aria-live=assertive, обычный статус — role=status/aria-live=polite. Критерии и локальные скриншоты на 1670x956 и 1280x800 сохранены в design-evidence/report.json и design-evidence/artifacts. FARO и записи проекта не изменялись.

При отказе API во время смены проекта SCAN сохраняет в рабочей области предыдущие сцены и список кандидатов, возвращает в localStorage последний успешно загруженный project ID и открывает его снова после перезагрузки. Это проверено синтетическим fetch-отказом в одной вкладке.

### Узкий экран и состояние слоёв — 24 октября 2026

На ширине 375 px первоначальный live QA обнаружил горизонтальное переполнение строки статуса и перекрытие нижним доком нижнего края второй сцены. Нижний док уменьшен до 150 px, сцены заканчиваются выше его верхней границы; строка статуса переносится на две строки и сохраняет все значения. Повторная проверка: viewport и ширина документа — 375 px, status `scrollWidth/clientWidth` — 375/375 px, сцены `[260, 418.5]` и `[425.5, 584]`, док начинается на 590 px. При 1670×956 две сцены остаются рядом, их ширина 796.5 px; документ не переполняется. Выключенные и недоступные слои станций, панорам и осей теперь имеют `aria-pressed=false`; облако проверено переключением туда и обратно. Снимки: [`scan-studio-1670x956-integrated.png`](../screenshots/scan-studio-1670x956-integrated.png), [`scan-studio-375x812-integrated.png`](../screenshots/scan-studio-375x812-integrated.png). Критерий Stage 3 по 60 FPS на целевой рабочей станции остаётся открытым.

### Проверка видимости слоёв

Live-проверка выявила, что внешние переключатели облака, кандидатов и BIM не меняли содержимое двух сцен; внутренние категории Viewer3D были скрыты вместе с HUD. Внешняя панель теперь управляет видимостью точек и контуров: candidates отображают только `unreviewed`, проверенная модель отображает `confirmed`/`corrected`, rejected/invalidated скрыты. Категории контуров становятся видимы, когда включён соответствующий слой. Панель слоёв сворачивается и располагается ниже командной ленты; каждый доступный слой можно нажать без перекрытых кликов. Отдельный тест покрывает четыре комбинации видимости.

Browser QA на live проекте подтвердил отображение кандидатов в обеих сценах, отдельное включение BIM и скрытие/возврат облака. При 1670×956 и 1280×800 `document.scrollWidth` равен ширине окна. Frontend `npm test`, TypeScript и production build прошли. Снимок: `../screenshots/scan-studio-layers-final.png`. Приёмка Stage 3 по FPS на целевой станции ещё не выполнена.
