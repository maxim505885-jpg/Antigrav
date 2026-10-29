# ReCap count probe for Revit 2027

This small Revit command cross-checks `RCProject.GetNumberOfPoints()` against
SCAN's native RCS stream and the count declared by the RCP manifest. Autodesk
documents `PointCloudType.GetReCapProject()` as the ReCap SDK entry point from
Revit and uses `RCProject.GetNumberOfPoints()` for the project total.

## Build and register

Run from this folder in PowerShell 7 on the .NET 10 runtime:

```powershell
pwsh -NoProfile -File .\build.ps1
pwsh -NoProfile -File .\install-user.ps1
```

The build uses the installed Revit 2027 API assemblies and PowerShell 7 on the
.NET 10 runtime; a separately installed .NET SDK is not required for this
small probe. Registration copies the DLL to
`%LOCALAPPDATA%\ScanStudio\Revit\2027` and adds a separate per-user Revit
manifest. The installer refuses unrelated manifest entries. To remove the
probe, run `uninstall-user.ps1`; removal checks the install receipt and DLL
hash first.
## Run

1. Start Revit 2027. A normal project may be open; from Revit Home the command creates a temporary metric project in memory and closes it without saving.
2. Choose **Add-Ins → External Tools → SCAN · сверка числа точек ReCap**.
3. Select `Симферополь легкий.rcp` from the 810-station FARO project.
4. The report is written under `%LOCALAPPDATA%\ScanStudio\diagnostics`.

The command hashes the selected RCP before and after the probe and refuses to
report success if its size or SHA-256 changes. It creates a temporary
`PointCloudType` inside a Revit transaction and rolls that transaction back.
It never writes to the RCP/RCS files or modifies the active RVT document after
rollback. The actual Revit-host run and GUI acceptance must still be recorded
separately; a successful build alone is not a count measurement.
