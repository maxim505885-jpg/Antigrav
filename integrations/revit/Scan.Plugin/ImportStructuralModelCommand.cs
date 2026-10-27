using System.Text.Json;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace Scan.Revit.Plugin;

[Transaction(TransactionMode.Manual)]
public sealed class ImportStructuralModelCommand : IExternalCommand
{
    private const string ApplicationId = "SCAN.StructuralModel/1.0";

    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        using var picker = new FileOpenDialog("SCAN BIM JSON (*.json)|*.json")
        {
            Title = "Выберите модель SCAN BIM JSON",
        };
        if (picker.Show() != ItemSelectionDialogResult.Confirmed)
            return Result.Cancelled;

        try
        {
            var selectedPath = ModelPathUtils.ConvertModelPathToUserVisiblePath(picker.GetSelectedModelPath());
            using var stream = File.OpenRead(selectedPath);
            using var json = JsonDocument.Parse(stream);
            var root = json.RootElement;
            if (RequiredString(root, "schema") != "scan2bim.bim/1.0")
                throw new InvalidDataException("Поддерживается только схема scan2bim.bim/1.0.");
            if (RequiredString(root, "units") != "m")
                throw new InvalidDataException("Единицы модели должны быть указаны в метрах (m).");
            ValidateCoordinateFrame(root);
            ValidateUniqueElementIds(root);

            var document = commandData.Application.ActiveUIDocument.Document;
            var counts = new ImportCounts();
            using var transaction = new Transaction(document, "Импорт модели SCAN BIM");
            transaction.Start();

            ImportLevels(document, root, counts);
            var existing = new FilteredElementCollector(document)
                .OfClass(typeof(DirectShape))
                .Cast<DirectShape>()
                .Where(shape => shape.ApplicationId == ApplicationId)
                .ToDictionary(shape => shape.ApplicationDataId, StringComparer.Ordinal);

            foreach (var item in root.GetProperty("elements").EnumerateArray())
            {
                var id = RequiredString(item, "id");
                if (string.IsNullOrWhiteSpace(id))
                {
                    counts.Unsupported++;
                    continue;
                }

                var hasPriorShape = existing.Remove(id, out var prior);
                if (!TryCreateShape(item, out var category, out var shapeGeometry, out var axisOnly))
                {
                    if (hasPriorShape && prior is not null)
                    {
                        document.Delete(prior.Id);
                        counts.RemovedUnsupported++;
                    }
                    counts.Unsupported++;
                    if (RequiredString(item, "class_name") == "truss")
                        counts.TrussEnvelopesSkipped++;
                    continue;
                }

                DirectShape shape;
                if (hasPriorShape && prior is not null && prior.Category.Id == category)
                {
                    shape = prior;
                    counts.Updated++;
                }
                else
                {
                    if (prior is not null)
                        document.Delete(prior.Id);
                    shape = DirectShape.CreateElement(document, category);
                    shape.ApplicationId = ApplicationId;
                    shape.ApplicationDataId = id;
                    counts.Created++;
                }

                shape.SetShape(new List<GeometryObject> { shapeGeometry });
                shape.ApplicationId = ApplicationId;
                shape.ApplicationDataId = id;
                SetComments(shape, item, id, axisOnly);
                if (axisOnly)
                    counts.MembersWithoutSection++;
                JsonElement? coordinateFrame = root.TryGetProperty("coordinate_frame", out var frame)
                    ? frame
                    : null;
                ElementProvenanceStorage.Attach(shape, ScanProvenancePayload.Serialize(
                    id, item, root.GetProperty("source"), coordinateFrame));
            }

            counts.Unchanged = existing.Count;
            transaction.Commit();
            Autodesk.Revit.UI.TaskDialog.Show(
                "SCAN BIM",
                $"Импорт завершён.\nСоздано: {counts.Created}\nОбновлено: {counts.Updated}\n" +
                $"Старые элементы сохранены: {counts.Unchanged}\n" +
                $"Удалено ставших неподдержанными: {counts.RemovedUnsupported}\n" +
                $"Оси без сечения (контур не придуман): {counts.MembersWithoutSection}\n" +
                $"Огибающие ферм без подтверждённых стержней: {counts.TrussEnvelopesSkipped}\n" +
                $"Неподдержанные: {counts.Unsupported}\n\n" +
                "Формы созданы как DirectShape. Сложные элементы не преобразуются в параметрические семейства."
            );
            return Result.Succeeded;
        }
        catch (Exception exception)
        {
            message = exception.Message;
            return Result.Failed;
        }
    }

    private static void ImportLevels(Document document, JsonElement root, ImportCounts counts)
    {
        if (!root.TryGetProperty("levels", out var levels) || levels.ValueKind != JsonValueKind.Array)
            return;

        foreach (var item in levels.EnumerateArray())
        {
            var elevation = ToInternal(RequiredNumber(item, "elevation"));
            var existing = new FilteredElementCollector(document)
                .OfClass(typeof(Level))
                .Cast<Level>()
                .FirstOrDefault(level => Math.Abs(level.Elevation - elevation) < ToInternal(0.001));
            if (existing is not null)
            {
                counts.LevelsReused++;
                continue;
            }

            var level = Level.Create(document, elevation);
            var label = item.TryGetProperty("name", out var name) ? name.GetString() : null;
            if (!string.IsNullOrWhiteSpace(label))
                level.Name = $"SCAN {label}";
            counts.LevelsCreated++;
        }
    }

    private static void ValidateCoordinateFrame(JsonElement root)
    {
        // Older 1.0 payloads predate this additive field and already use source-cloud coordinates.
        if (!root.TryGetProperty("coordinate_frame", out var frame))
            return;
        if (frame.ValueKind != JsonValueKind.Object
            || RequiredString(frame, "id") != "source_cloud_world"
            || RequiredString(frame, "units") != "m"
            || RequiredString(frame, "vertical_axis") != "Z")
            throw new InvalidDataException("Revit импортирует только frame source_cloud_world в метрах с вертикальной осью Z.");
    }

    private static void ValidateUniqueElementIds(JsonElement root)
    {
        if (!root.TryGetProperty("elements", out var items) || items.ValueKind != JsonValueKind.Array)
            throw new InvalidDataException("В BIM JSON ожидается массив elements.");
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var item in items.EnumerateArray())
        {
            var id = RequiredString(item, "id");
            if (string.IsNullOrWhiteSpace(id) || !seen.Add(id))
                throw new InvalidDataException($"BIM JSON содержит пустой или повторный ID элемента: '{id}'.");
        }
    }

    private static bool TryCreateShape(JsonElement item, out ElementId category, out GeometryObject shapeGeometry, out bool axisOnly)
    {
        var className = RequiredString(item, "class_name");
        category = new ElementId(className switch
        {
            "column" => BuiltInCategory.OST_StructuralColumns,
            "beam" or "girder" or "brace" or "truss" => BuiltInCategory.OST_StructuralFraming,
            "slab" => BuiltInCategory.OST_Floors,
            _ => BuiltInCategory.OST_GenericModel,
        });
        shapeGeometry = null!;
        axisOnly = false;

        if (!item.TryGetProperty("geometry", out var geometry))
            return false;
        var kind = RequiredString(geometry, "kind");
        // A truss envelope is not the truss itself. Keep it visible as unsupported
        // until the exchange schema carries its individual members and assembly.
        if (className == "truss")
            return false;
        if (kind == "oriented_box")
        {
            var center = Vector(geometry.GetProperty("center"));
            var sizes = geometry.GetProperty("sizes");
            var length = ToInternal(RequiredNumber(sizes, "length"));
            var width = ToInternal(RequiredNumber(sizes, "thickness"));
            var height = ToInternal(RequiredNumber(sizes, "height"));
            var angle = OptionalNumber(geometry, "rotation_z", 0.0);
            var ca = Math.Cos(angle);
            var sa = Math.Sin(angle);
            var localX = new XYZ(ca, sa, 0.0);
            var localY = new XYZ(-sa, ca, 0.0);
            var baseCenter = center - XYZ.BasisZ * (height / 2.0);
            var corners = new[]
            {
                baseCenter - localX * (length / 2) - localY * (width / 2),
                baseCenter + localX * (length / 2) - localY * (width / 2),
                baseCenter + localX * (length / 2) + localY * (width / 2),
                baseCenter - localX * (length / 2) + localY * (width / 2),
            };
            shapeGeometry = ExtrudeRectangle(corners, XYZ.BasisZ, height);
            return true;
        }

        if (kind == "member")
        {
            if (!MemberAxisPolicy.TryRead(geometry, out _, out _))
                return false;

            var geometryStart = Vector(geometry.GetProperty("p0"));
            var geometryEnd = Vector(geometry.GetProperty("p1"));
            var delta = geometryEnd - geometryStart;
            var length = delta.GetLength();
            if (length < 1e-6)
                return false;
            if (!MemberSectionPolicy.TryGetPositiveSectionMetres(geometry, out var sectionMetres))
            {
                // Preserve the measured/proposed centerline without pretending
                // the cross-section was observed. DirectShape accepts Curves.
                shapeGeometry = Line.CreateBound(geometryStart, geometryEnd);
                axisOnly = true;
                return true;
            }
            var axis = delta / length;
            var helper = Math.Abs(axis.DotProduct(XYZ.BasisZ)) > 0.9 ? XYZ.BasisY : XYZ.BasisZ;
            var localX = axis.CrossProduct(helper).Normalize();
            var localY = axis.CrossProduct(localX).Normalize();
            var section = ToInternal(sectionMetres);
            var corners = new[]
            {
                geometryStart - localX * (section / 2) - localY * (section / 2),
                geometryStart + localX * (section / 2) - localY * (section / 2),
                geometryStart + localX * (section / 2) + localY * (section / 2),
                geometryStart - localX * (section / 2) + localY * (section / 2),
            };
            shapeGeometry = ExtrudeRectangle(corners, axis, length);
            return true;
        }

        if (className == "slab" && kind == "slab"
            && SlabGeometryPolicy.TryRead(geometry, out var polygon, out var elevation, out var thickness))
        {
            var baseZ = ToInternal(elevation - thickness / 2.0);
            var corners = polygon.Select(point => new XYZ(ToInternal(point.X), ToInternal(point.Y), baseZ)).ToArray();
            shapeGeometry = ExtrudePolygon(corners, thickness);
            return true;
        }

        return false;
    }

    private static Solid ExtrudePolygon(IReadOnlyList<XYZ> corners, double thicknessMetres)
    {
        var loop = new CurveLoop();
        for (var index = 0; index < corners.Count; index++)
            loop.Append(Line.CreateBound(corners[index], corners[(index + 1) % corners.Count]));
        return GeometryCreationUtilities.CreateExtrusionGeometry(
            new List<CurveLoop> { loop }, XYZ.BasisZ, ToInternal(thicknessMetres));
    }

    private static Solid ExtrudeRectangle(IReadOnlyList<XYZ> corners, XYZ direction, double depth)
    {
        var loop = new CurveLoop();
        for (var index = 0; index < corners.Count; index++)
            loop.Append(Line.CreateBound(corners[index], corners[(index + 1) % corners.Count]));
        return GeometryCreationUtilities.CreateExtrusionGeometry(
            new List<CurveLoop> { loop }, direction.Normalize(), depth);
    }

    private static void SetComments(DirectShape shape, JsonElement item, string id, bool axisOnly)
    {
        if (shape.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS) is not { IsReadOnly: false } comments)
            return;
        var className = RequiredString(item, "class_name");
        var status = item.TryGetProperty("review_status", out var review) ? review.GetString() : "unreviewed";
        var geometryNote = axisOnly ? "; GEOMETRY=AXIS_ONLY; SECTION=UNKNOWN" : string.Empty;
        comments.Set($"SCAN_ID={id}; CLASS={className}; REVIEW={status}{geometryNote}");
    }

    private static XYZ Vector(JsonElement value)
    {
        if (value.ValueKind != JsonValueKind.Array || value.GetArrayLength() != 3)
            throw new InvalidDataException("Ожидается координата из трёх чисел.");
        return new XYZ(
            ToInternal(value[0].GetDouble()),
            ToInternal(value[1].GetDouble()),
            ToInternal(value[2].GetDouble()));
    }

    private static double ToInternal(double metres) => UnitUtils.ConvertToInternalUnits(metres, UnitTypeId.Meters);

    private static string RequiredString(JsonElement value, string property) =>
        value.TryGetProperty(property, out var item) && item.ValueKind == JsonValueKind.String
            ? item.GetString() ?? string.Empty
            : throw new InvalidDataException($"В BIM JSON отсутствует строка '{property}'.");

    private static double RequiredNumber(JsonElement value, string property) =>
        value.TryGetProperty(property, out var item) && item.TryGetDouble(out var number) && double.IsFinite(number)
            ? number
            : throw new InvalidDataException($"В BIM JSON отсутствует число '{property}'.");

    private static double OptionalNumber(JsonElement value, string property, double fallback) =>
        value.TryGetProperty(property, out var item) && item.TryGetDouble(out var number) && double.IsFinite(number)
            ? number
            : fallback;

    private sealed class ImportCounts
    {
        public int Created { get; set; }
        public int Updated { get; set; }
        public int Unchanged { get; set; }
        public int RemovedUnsupported { get; set; }
        public int Unsupported { get; set; }
        public int MembersWithoutSection { get; set; }
        public int TrussEnvelopesSkipped { get; set; }
        public int LevelsCreated { get; set; }
        public int LevelsReused { get; set; }
    }
}
