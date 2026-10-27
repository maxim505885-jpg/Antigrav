using System.Text.Json;
using System.Text.Json.Nodes;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace Scan.Revit.Plugin;

[Transaction(TransactionMode.ReadOnly)]
public sealed class VerifyImportedModelCommand : IExternalCommand
{
    private const string ApplicationId = "SCAN.StructuralModel/1.0";

    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        using var picker = new FileOpenDialog("Исходная модель SCAN BIM JSON (*.json)|*.json")
        {
            Title = "Выберите исходный SCAN BIM JSON для сверки",
        };
        if (picker.Show() != ItemSelectionDialogResult.Confirmed)
            return Result.Cancelled;

        try
        {
            var sourcePath = ModelPathUtils.ConvertModelPathToUserVisiblePath(picker.GetSelectedModelPath());
            using var sourceDocument = JsonDocument.Parse(File.ReadAllText(sourcePath));
            var root = sourceDocument.RootElement;
            if (root.GetProperty("schema").GetString() != "scan2bim.bim/1.0")
                throw new InvalidDataException("Поддерживается только схема scan2bim.bim/1.0.");

            var source = root.GetProperty("source");
            JsonElement? frame = root.TryGetProperty("coordinate_frame", out var frameValue) ? frameValue : null;
            var sourceElements = root.GetProperty("elements").EnumerateArray().ToList();
            var expected = sourceElements.Where(RevitImportAuditPolicy.IsExpectedToImport)
                .ToDictionary(item => item.GetProperty("id").GetString() ?? string.Empty, StringComparer.Ordinal);
            var intentionallySkipped = sourceElements.Where(item => !RevitImportAuditPolicy.IsExpectedToImport(item))
                .Select(item => item.TryGetProperty("id", out var id) ? id.GetString() ?? string.Empty : string.Empty)
                .Order(StringComparer.Ordinal).ToArray();
            if (expected.ContainsKey(string.Empty))
                throw new InvalidDataException("Исходный BIM JSON содержит пустой ID элемента.");

            var document = commandData.Application.ActiveUIDocument.Document;
            var actual = new FilteredElementCollector(document)
                .OfClass(typeof(DirectShape))
                .Cast<DirectShape>()
                .Where(shape => shape.ApplicationId == ApplicationId)
                .ToList();
            var grouped = actual.GroupBy(shape => shape.ApplicationDataId ?? string.Empty, StringComparer.Ordinal)
                .ToDictionary(group => group.Key, group => group.ToList(), StringComparer.Ordinal);
            var missing = new List<string>();
            var duplicates = grouped.Where(pair => pair.Value.Count > 1).Select(pair => pair.Key).Order().ToList();
            var provenanceMismatches = new List<string>();
            var categoryMismatches = new List<string>();

            foreach (var pair in expected)
            {
                if (!grouped.TryGetValue(pair.Key, out var matches) || matches.Count == 0)
                {
                    missing.Add(pair.Key);
                    continue;
                }
                if (matches.Count != 1)
                    continue;

                var element = pair.Value;
                var expectedCategory = CategoryFor(element.GetProperty("class_name").GetString() ?? string.Empty);
                if (expectedCategory is not null && matches[0].Category.Id != new ElementId(expectedCategory.Value))
                    categoryMismatches.Add(pair.Key);

                var expectedPayload = ScanProvenancePayload.Serialize(pair.Key, element, source, frame);
                if (!ElementProvenanceStorage.TryRead(matches[0], out var actualPayload)
                    || !JsonNode.DeepEquals(JsonNode.Parse(expectedPayload), JsonNode.Parse(actualPayload)))
                    provenanceMismatches.Add(pair.Key);
            }

            var unexpected = grouped.Keys
                .Where(id => !expected.ContainsKey(id))
                .Order(StringComparer.Ordinal)
                .ToList();
            var pass = missing.Count == 0 && duplicates.Count == 0
                && provenanceMismatches.Count == 0 && categoryMismatches.Count == 0;
            var report = new
            {
                schema = "scan2bim.revit-import-audit/1.0",
                created_at_utc = DateTimeOffset.UtcNow,
                result = pass ? "PASS" : "FAIL",
                source_file = Path.GetFullPath(sourcePath),
                revit_document = document.PathName,
                revit_title = document.Title,
                source_element_count = sourceElements.Count,
                expected_element_count = expected.Count,
                intentionally_skipped_source_ids = intentionallySkipped,
                imported_scan_shape_count = actual.Count,
                matched_unique_ids = expected.Count - missing.Count - duplicates.Sum(id => Math.Max(0, grouped[id].Count - 1)),
                missing_ids = missing.Order(StringComparer.Ordinal).ToArray(),
                duplicate_ids = duplicates,
                unexpected_scan_ids = unexpected,
                provenance_mismatch_ids = provenanceMismatches.Order(StringComparer.Ordinal).ToArray(),
                category_mismatch_ids = categoryMismatches.Order(StringComparer.Ordinal).ToArray(),
                geometry_visual_review_required = true,
                limitation = "This report verifies SCAN IDs, categories and stored provenance after reopen; it does not measure geometric deviation from the source cloud.",
            };

            using var save = new FileSaveDialog("JSON report (*.json)|*.json")
            {
                Title = "Сохранить отчёт сверки SCAN BIM",
                InitialFileName = $"SCAN_Revit_Audit_{DateTime.Now:yyyyMMdd_HHmmss}.json",
            };
            if (save.Show() != ItemSelectionDialogResult.Confirmed)
                return Result.Cancelled;
            var reportPath = ModelPathUtils.ConvertModelPathToUserVisiblePath(save.GetSelectedModelPath());
            File.WriteAllText(reportPath, JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));

            TaskDialog.Show("SCAN BIM — проверка модели",
                $"Результат: {(pass ? "ПРОЙДЕНА" : "ЕСТЬ РАСХОЖДЕНИЯ")}\n" +
                $"ID в исходнике: {expected.Count}\nSCAN-элементов в Revit: {actual.Count}\n" +
                $"Отсутствующих ID: {missing.Count}\nДубликатов: {duplicates.Count}\n" +
                $"Несовпадений происхождения: {provenanceMismatches.Count}\n" +
                $"Несовпадений категорий: {categoryMismatches.Count}\n\nОтчёт: {reportPath}\n\n" +
                "Геометрию всё ещё нужно визуально проверить в Revit.");
            return Result.Succeeded;
        }
        catch (Exception exception)
        {
            message = exception.Message;
            return Result.Failed;
        }
    }

    private static BuiltInCategory? CategoryFor(string className) => className switch
    {
        "column" => BuiltInCategory.OST_StructuralColumns,
        "beam" or "girder" or "brace" or "truss" => BuiltInCategory.OST_StructuralFraming,
        "slab" => BuiltInCategory.OST_Floors,
        _ => BuiltInCategory.OST_GenericModel,
    };
}
