# Проверка импорта в Revit 2027

Статус на 21 октября 2026: плагин собирается, но в текущем проходе ещё не загружался в Revit; интерактивная приёмка остаётся открытой. Тестовые файлы синтетические, не содержат данных FARO и не требуют исходного `1.rcs`.

## Подготовка

Из корня репозитория собрать плагин и один раз создать сценарии импорта:

```powershell
$env:DOTNET_CLI_HOME = Join-Path $PWD 'data/.dotnet-cli-home'
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'
& .\data\.tools\dotnet10\dotnet.exe build integrations/revit/Scan.Plugin/Scan.Plugin.csproj -c Release
.\.venv\Scripts\python.exe -B scripts/create_revit_pilot_fixtures.py
```

Генератор не перезаписывает готовые файлы. Контрактные тесты проверяют BIM JSON v1 и v2, последовательность ID, изменённую геометрию и намеренно испорченный rollback-файл:

```powershell
$env:S2B_DATA_DIR = Join-Path $PWD 'data/validation/pytest-revit-fixtures'
.\.venv\Scripts\python.exe -B -m pytest backend/tests/test_revit_pilot_fixtures.py -q -p no:cacheprovider --tb=short
```

Зарегистрировать `integrations/revit/Scan.Plugin/install-user.ps1`, перезапустить Revit 2027 и создать отдельный проект из стандартного шаблона. Сохранить его как `data/validation/revit-pilot/revit-import-test.rvt`; для проверки отката использовать копию RVT. Исходные модели и облака не открывать.

## Сценарии и ожидаемое поведение

| Шаг | Действие | Ожидаемые счётчики | Проверка модели |
|---|---|---|---|
| 1 | Импортировать `integrations/revit/pilot/import-run-1.json` | Создано 4, обновлено 0, неподдержано 0 | Уникальные SCAN IDs `SCAN-COL-KEEP`, `SCAN-COL-CHANGE`, `SCAN-COL-OMIT`, `SCAN-BEAM-KEEP`; 2 уровня из JSON созданы или переиспользованы по высоте |
| 2 | Импортировать `import-run-2.json` | Создано 0, обновлено 3, сохранено отсутствующих 1, неподдержано 1 | Геометрия `SCAN-COL-CHANGE` изменилась; `SCAN-COL-OMIT` осталась; ферма `SCAN-TRUSS-UNSUPPORTED` не создана и посчитана как unsupported |
| 3 | Повторно импортировать `import-run-2.json` | Создано 0, обновлено 3, сохранено отсутствующих 1, неподдержано 1 | Нет дубликатов SCAN ID; отсутствующая колонна остаётся |
| 4 | Открыть копию чистого RVT и импортировать `rollback-invalid-geometry.json` | Команда завершается ошибкой | В транзакции не остаются тестовая колонна `SCAN-ROLLBACK-COLUMN` и уровень 99 м; этим проверяется откат после частично выполненных операций |

Число уровней, созданных/переиспользованных, может зависеть от уровней исходного Revit-шаблона; фиксировать фактические значения отдельно. Импортёр создаёт `DirectShape`, а не параметрические семейства. Сохранить RVT, закрыть Revit, открыть его повторно и сверить ID/количество с таблицей. Записать build Revit, имя/хеш шаблона, скриншоты, счётчики диалога и SHA JSON в этот протокол; не отмечать Task 9 завершённым до проверки фактического RVT.

## Выполненная автоматическая проверка

- `create_revit_pilot_fixtures.py` создал три отдельных файла без пользовательских облаков.
- `test_revit_pilot_fixtures.py` проверил v1/v2 по контракту `scan2bim.bim/1.0`, подтверждает изменённую геометрию под прежним ID и один пропущенный ID; rollback JSON намеренно не проходит BIM Schema, чтобы вызвать ошибку уже после старта транзакции.
- Свежая сборка Revit 2027: 0 ошибок, 3 предупреждения Autodesk/.NET reference assemblies.
- Импорт в UI, транзакционный rollback внутри Revit и RVT round-trip пока не выполнены; этот набор только готовит воспроизводимую приёмку.

## Повторная проверка сборки и запуска Revit — 21 октября 2026

- Манифест `SCAN.StructuralModel.addin` уже существует в пользовательском каталоге Revit 2027 и указывает на текущую `Scan.Revit.Plugin.dll`; повторная регистрация не выполнялась, чтобы не перезаписывать файл вне проекта.
- Два теста `test_revit_pilot_fixtures.py` прошли. Повторный `dotnet build ... -c Release --no-restore` завершился успешно: 0 ошибок, 3 предупреждения разрешения Autodesk API assembly references. Обычный build без `--no-restore` не смог прочитать пользовательский `NuGet.Config` из-за WinError 5, поэтому использованы сохранённые restore assets.
- Запуск установленного `Revit.exe` через управляемое приложение завершился сообщением `Computer Use app approval timed out`; после проверки список окон Revit пуст. Следовательно, add-in не загружался, тестовые сценарии и RVT round-trip не выполнялись. Повторять нельзя засчитать как успешную интерактивную приёмку.
