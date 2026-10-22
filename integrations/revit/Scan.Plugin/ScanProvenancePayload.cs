using System.Text.Json;

namespace Scan.Revit.Plugin;

internal static class ScanProvenancePayload
{
    public static string Serialize(
        string id,
        JsonElement element,
        JsonElement source,
        JsonElement? coordinateFrame)
    {
        var payload = new
        {
            schema = "scan2bim.revit-provenance/1.0",
            source,
            coordinateFrame,
            element = new
            {
                id,
                className = element.GetProperty("class_name"),
                reviewStatus = element.TryGetProperty("review_status", out var review)
                    ? review
                    : ParseDefault("\"unreviewed\""),
                dimensions = element.TryGetProperty("dimensions", out var dimensions)
                    ? dimensions
                    : ParseDefault("{}"),
                metadata = element.TryGetProperty("metadata", out var metadata)
                    ? metadata
                    : ParseDefault("{}"),
            },
        };
        return JsonSerializer.Serialize(payload);
    }

    private static JsonElement ParseDefault(string json)
    {
        using var document = JsonDocument.Parse(json);
        return document.RootElement.Clone();
    }
}
