# SCAN Revit 2027 add-in

The add-in imports `scan2bim.bim/1.0` JSON in metres. It creates or updates
columns, linear members and polygonal slabs as Revit `DirectShape` geometry
(slabs use the `Floors` category), and reuses levels at matching elevations.
Members without a verified positive section are imported as centerline curves,
with `GEOMETRY=AXIS_ONLY; SECTION=UNKNOWN` in Comments; the importer does not
invent a cross-section. Truss envelope rows are skipped because they are not
truss solids; the observed member rows remain individual line geometry.
Slab elevation is interpreted as the center plane and the extrusion starts at
`z - thickness/2`, matching the IFC export convention. SCAN element IDs are
stored as `ApplicationDataId` and in the instance Comments parameter, so a
second import updates the existing shape.
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

The Revit 2027 API uses .NET 10. Build with .NET SDK 10.0.100 (or a compatible
.NET 10 SDK) and the Revit API assemblies installed at
`C:\Program Files\Autodesk\Revit 2027`:

```powershell
dotnet restore integrations/revit/Scan.Plugin/Scan.Plugin.csproj
dotnet build integrations/revit/Scan.Plugin/Scan.Plugin.csproj -c Release --no-restore
```

After build, run `integrations/revit/Scan.Plugin/install-user.ps1`. It copies the
DLL into `%LOCALAPPDATA%\ScanStudio\Revit\2027` and registers both commands in
the current user's Revit 2027 AddIns folder. The guarded
`integrations/revit/Scan.Plugin/uninstall-user.ps1` removes only files recorded
in its install receipt. Restart Revit, use **Add-Ins → External Tools → Импорт
SCAN BIM JSON**, and select a SCAN export. Review the model in a disposable RVT
first; a successful build is not host acceptance.

The add-in also provides **Сверить модель с исходником**. After importing and
saving the RVT, close and reopen it, run this command, select the same BIM JSON,
and save the audit report. A passing report checks unique SCAN IDs, expected
Revit categories, and stored source/review/dimension provenance. It deliberately
requires visual geometry review; it does not claim measured accuracy.

For a deterministic repeat-import, absent-ID preservation and rollback check,
use the synthetic fixtures in `integrations/revit/pilot/` and follow
`docs/validation/REVIT_PILOT.md`. The fixtures contain no FARO source data.