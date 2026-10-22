# SCAN Revit 2027 add-in

The add-in imports `scan2bim.bim/1.0` JSON in metres. It creates or updates
columns and linear members as Revit `DirectShape` solids and reuses levels at
matching elevations. SCAN element IDs are stored as `ApplicationDataId` and in
the instance Comments parameter, so a second import updates the existing shape.
New exports identify `source_cloud_world` coordinates, metres and a Z vertical
axis. The importer validates that frame when present and rejects duplicate or
empty element IDs before opening a Revit transaction. Older 1.0 files without
the additive frame descriptor remain supported.

The output is editable as DirectShape geometry and carries element class and
review status. A versioned SCAN Extensible Storage entity also keeps the source
cloud snapshot, coordinate frame, element dimensions and recognition metadata,
including sampled source point-row IDs. It is not a parametric family.
Unsupported or malformed geometries are counted and skipped. If an incoming ID
becomes unsupported, its old SCAN shape is removed in the same transaction and
counted separately so stale geometry is not shown as current; shapes whose IDs
are absent from the incoming JSON are preserved.

## Build

Autodesk's Revit 2027 API uses .NET 10 and the add-in was built with SDK
10.0.100. In this workspace the SDK lives in the ignored `data/.tools`
directory; build from the repository root with:

```powershell
.\data\.tools\dotnet10\dotnet.exe build integrations/revit/Scan.Plugin/Scan.Plugin.csproj -c Release
```

The project references the Revit 2027 API assemblies from
`C:\Program Files\Autodesk\Revit 2027`. Override `RevitInstallDir` for a
different installation. After build, run `install-user.ps1` to register the
command under the current Windows user's Revit 2027 AddIns folder. Restart
Revit, use **Add-Ins → External Tools → Импорт SCAN BIM JSON**, and select a
JSON file exported by SCAN. Review the model in a disposable RVT first; the
add-in has compiled, but has not yet been loaded into Revit in this workspace.

For a deterministic repeat-import, absent-ID preservation and rollback check,
use the synthetic fixtures in `integrations/revit/pilot/` and follow
`docs/validation/REVIT_PILOT.md`. The fixtures contain no FARO source data.
