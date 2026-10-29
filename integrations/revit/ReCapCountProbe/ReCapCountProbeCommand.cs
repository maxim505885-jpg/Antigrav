#nullable enable
using System;
using System.IO;
using System.Security.Cryptography;
using System.Globalization;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace Scan.Revit.ReCapCountProbe;

[Transaction(TransactionMode.Manual)]
public sealed class ReCapCountProbeCommand : IExternalCommand
{
    private const string InputEnvironmentVariable = "SCAN_RECAP_COUNT_PROBE_RCP";
    private const string OutputEnvironmentVariable = "SCAN_RECAP_COUNT_PROBE_OUTPUT";

    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        string? sourcePath = Environment.GetEnvironmentVariable(InputEnvironmentVariable);
        if (string.IsNullOrWhiteSpace(sourcePath))
        {
            using var picker = new FileOpenDialog("Autodesk ReCap project (*.rcp)|*.rcp")
            {
                Title = "Выберите RCP для независимой сверки числа точек",
            };
            if (picker.Show() != ItemSelectionDialogResult.Confirmed)
                return Result.Cancelled;
            sourcePath = ModelPathUtils.ConvertModelPathToUserVisiblePath(picker.GetSelectedModelPath());
        }

        sourcePath = Path.GetFullPath(sourcePath);
        if (!File.Exists(sourcePath) || !string.Equals(Path.GetExtension(sourcePath), ".rcp", StringComparison.OrdinalIgnoreCase))
        {
            message = "RCP-файл не найден или выбран файл другого формата.";
            TaskDialog.Show("SCAN · аудит ReCap", message);
            return Result.Failed;
        }

        var before = HashFile(sourcePath);
        var document = commandData.Application.ActiveUIDocument?.Document;
        var temporaryDocument = document is null || document.IsFamilyDocument;
        if (temporaryDocument)
        {
            // The probe must also work from Revit Home without requiring a user RVT.
            // This document exists only in memory and is always closed without saving.
            document = commandData.Application.Application.NewProjectDocument(UnitSystem.Metric);
        }

        (long Length, string Sha256) after = default;
        ulong pointCount;
        try
        {
            using (var transaction = new Transaction(document!, "SCAN · временное чтение RCP point count"))
            {
                transaction.Start();
                try
                {
                    var pointCloudType = PointCloudType.Create(document!, "rcp", sourcePath);
                    var recapProject = pointCloudType.GetReCapProject();
                    pointCount = recapProject.GetNumberOfPoints();
                }
                finally
                {
                    if (transaction.GetStatus() == TransactionStatus.Started)
                        transaction.RollBack();
                }
            }
            after = HashFile(sourcePath);
            if (!string.Equals(before.Sha256, after.Sha256, StringComparison.OrdinalIgnoreCase)
                || before.Length != after.Length)
            {
                message = "Контроль RCP не пройден: файл изменился во время чтения.";
                TaskDialog.Show("SCAN · аудит ReCap", message);
                return Result.Failed;
            }
        }
        finally
        {
            if (temporaryDocument)
                document!.Close(false);
        }

        var outputPath = Environment.GetEnvironmentVariable(OutputEnvironmentVariable);
        if (string.IsNullOrWhiteSpace(outputPath))
        {
            var outputDirectory = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "ScanStudio",
                "diagnostics");
            Directory.CreateDirectory(outputDirectory);
            outputPath = Path.Combine(outputDirectory, $"recap-count-{DateTimeOffset.UtcNow:yyyyMMdd-HHmmss}.json");
        }
        outputPath = Path.GetFullPath(outputPath);
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);

        var json = "{\n" +
            $"  \"schema\": {JsonQuote("scan2bim.recap-count-probe/1.0")},\n" +
            $"  \"status\": {JsonQuote("observed")},\n" +
            $"  \"authority\": {JsonQuote("Autodesk Revit 2027 host API")},\n" +
            $"  \"observed_at_utc\": {JsonQuote(DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture))},\n" +
            $"  \"source_rcp\": {JsonQuote(sourcePath)},\n" +
            $"  \"source_size_bytes\": {after.Length.ToString(CultureInfo.InvariantCulture)},\n" +
            $"  \"source_sha256_before\": {JsonQuote(before.Sha256)},\n" +
            $"  \"source_sha256_after\": {JsonQuote(after.Sha256)},\n" +
            $"  \"recap_project_point_count\": {pointCount.ToString(CultureInfo.InvariantCulture)},\n" +
            $"  \"revit_version\": {JsonQuote(commandData.Application.Application.VersionNumber)},\n" +
            $"  \"transaction\": {JsonQuote("rolled_back")},\n" +
            $"  \"revit_document\": {JsonQuote(temporaryDocument ? "temporary_unsaved_project" : "active_project")},\n" +
            $"  \"temporary_document_discarded_without_saving\": {(temporaryDocument ? "true" : "false")},\n" +
            "  \"source_mutated\": false\n" +
            "}";
        File.WriteAllText(outputPath, json + Environment.NewLine);
        TaskDialog.Show("SCAN · аудит ReCap", $"RCP points: {pointCount:N0}\nИсточник не изменён.\nОтчёт: {outputPath}");
        return Result.Succeeded;
    }

    private static string JsonQuote(string value)
    {
        var builder = new StringBuilder(value.Length + 2);
        builder.Append('"');
        foreach (var character in value)
        {
            switch (character)
            {
                case '"': builder.Append("\\\""); break;
                case '\\': builder.Append("\\\\"); break;
                case '\b': builder.Append("\\b"); break;
                case '\f': builder.Append("\\f"); break;
                case '\n': builder.Append("\\n"); break;
                case '\r': builder.Append("\\r"); break;
                case '\t': builder.Append("\\t"); break;
                default:
                    if (character < ' ')
                    {
                        builder.Append("\\u").Append(((int)character).ToString("x4", CultureInfo.InvariantCulture));
                    }
                    else
                    {
                        builder.Append(character);
                    }
                    break;
            }
        }
        return builder.Append('"').ToString();
    }

    private static (long Length, string Sha256) HashFile(string path)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        return (stream.Length, Convert.ToHexString(SHA256.HashData(stream)));
    }
}
