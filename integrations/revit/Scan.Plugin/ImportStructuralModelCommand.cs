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

                if (!TryCreateShape(item, out var category, out var solid))
                {
                    counts.Unsupported++;
                    continue;
                }

                DirectShape shape;
                if (existing.Remove(id, out var prior) && prior.Category.Id == category)
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

                shape.SetShape(new List<GeometryObject> { solid });
                shape.ApplicationId = ApplicationId;
                shape.ApplicationDataId = id;
                SetComments(shape, item, id);
            }

            counts.Unchanged = existing.Count;
            transaction.Commit();
            Autodesk.Revit.UI.TaskDialog.Show(
                "SCAN BIM",
                $"Импорт завершён.\nСоздано: {counts.Created}\nОбновлено: {counts.Updated}\n" +
                $"Старые элементы сохранены: {counts.Unchanged}\nНеподдержанные: {counts.Unsupported}\n\n" +
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

    private static bool TryCreateShape(JsonElement item, out ElementId category, out Solid solid)
    {
        var className = RequiredString(item, "class_name");
        category = new ElementId(className switch
        {
            "column" => BuiltInCategory.OST_StructuralColumns,
            "beam" or "girder" or "brace" or "truss" => BuiltInCategory.OST_StructuralFraming,
            _ => BuiltInCategory.OST_GenericModel,
        });
        solid = null!;

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
            solid = ExtrudeRectangle(corners, XYZ.BasisZ, height);
            return true;
        }

        if (kind == "member")
        {
            var geometryStart = Vector(geometry.GetProperty("p0"));
            var geometryEnd = Vector(geometry.GetProperty("p1"));
            var delta = geometryEnd - geometryStart;
            var length = delta.GetLength();
            if (length < 1e-6)
                return false;
            var axis = delta / length;
            var helper = Math.Abs(axis.DotProduct(XYZ.BasisZ)) > 0.9 ? XYZ.BasisY : XYZ.BasisZ;
            var localX = axis.CrossProduct(helper).Normalize();
            var localY = axis.CrossProduct(localX).Normalize();
            var section = ToInternal(OptionalNumber(geometry, "section_m", 0.15));
            var corners = new[]
            {
                geometryStart - localX * (section / 2) - localY * (section / 2),
                geometryStart + localX * (section / 2) - localY * (section / 2),
                geometryStart + localX * (section / 2) + localY * (section / 2),
                geometryStart - localX * (section / 2) + localY * (section / 2),
            };
            solid = ExtrudeRectangle(corners, axis, length);
            return true;
        }

        return false;
    }

    private static Solid ExtrudeRectangle(IReadOnlyList<XYZ> corners, XYZ direction, double depth)
    {
        var loop = new CurveLoop();
        for (var index = 0; index < corners.Count; index++)
            loop.Append(Line.CreateBound(corners[index], corners[(index + 1) % corners.Count]));
        return GeometryCreationUtilities.CreateExtrusionGeometry(
            new List<CurveLoop> { loop }, direction.Normalize(), depth);
    }

    private static void SetComments(DirectShape shape, JsonElement item, string id)
    {
        if (shape.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS) is not { IsReadOnly: false } comments)
            return;
        var className = RequiredString(item, "class_name");
        var status = item.TryGetProperty("review_status", out var review) ? review.GetString() : "unreviewed";
        comments.Set($"SCAN_ID={id}; CLASS={className}; REVIEW={status}");
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
        public int Unsupported { get; set; }
        public int LevelsCreated { get; set; }
        public int LevelsReused { get; set; }
    }
}
