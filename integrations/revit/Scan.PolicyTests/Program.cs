using System.Text.Json;
using Scan.Revit.Plugin;

var cases = new (string Json, bool Expected, double Section)[]
{
    ("{\"kind\":\"member\",\"section_m\":0.25}", true, 0.25),
    ("{\"kind\":\"member\"}", false, 0),
    ("{\"kind\":\"member\",\"section_m\":null}", false, 0),
    ("{\"kind\":\"member\",\"section_m\":\"0.15\"}", false, 0),
    ("{\"kind\":\"member\",\"section_m\":0}", false, 0),
    ("{\"kind\":\"member\",\"section_m\":-0.1}", false, 0),
    ("{\"kind\":\"member\",\"section_m\":1e999}", false, 0),
};

foreach (var (json, expected, expectedSection) in cases)
{
    using var document = JsonDocument.Parse(json);
    var supported = MemberSectionPolicy.TryGetPositiveSectionMetres(document.RootElement, out var section);
    if (supported != expected || (supported && Math.Abs(section - expectedSection) > 1e-12))
        throw new InvalidOperationException($"Section policy mismatch for {json}: supported={supported}, section={section}");
}

const string elementJson = "{\"class_name\":\"beam\",\"review_status\":\"unreviewed\",\"dimensions\":{\"role\":\"crane_girder\"},\"metadata\":{\"source_point_ids\":[11,17,23],\"source_point_id_space\":\"positions.npy row index\"}}";
const string sourceJson = "{\"cloud_id\":\"cloud-1\",\"snapshot_manifest\":{\"sha256\":\"abc123\"}}";
const string frameJson = "{\"id\":\"source_cloud_world\",\"units\":\"m\",\"vertical_axis\":\"Z\"}";
using var elementDocument = JsonDocument.Parse(elementJson);
using var sourceDocument = JsonDocument.Parse(sourceJson);
using var frameDocument = JsonDocument.Parse(frameJson);
var payloadJson = ScanProvenancePayload.Serialize(
    "member-1", elementDocument.RootElement, sourceDocument.RootElement, frameDocument.RootElement);
using var payload = JsonDocument.Parse(payloadJson);
var root = payload.RootElement;
if (root.GetProperty("schema").GetString() != "scan2bim.revit-provenance/1.0"
    || root.GetProperty("source").GetProperty("snapshot_manifest").GetProperty("sha256").GetString() != "abc123"
    || root.GetProperty("coordinateFrame").GetProperty("id").GetString() != "source_cloud_world"
    || root.GetProperty("element").GetProperty("metadata").GetProperty("source_point_ids")[1].GetInt32() != 17)
    throw new InvalidOperationException("Revit provenance payload lost source, frame or point-row evidence.");

const string legacyElementJson = "{\"class_name\":\"beam\"}";
using var legacyDocument = JsonDocument.Parse(legacyElementJson);
var legacyPayloadJson = ScanProvenancePayload.Serialize(
    "legacy-member", legacyDocument.RootElement, sourceDocument.RootElement, null);
using var legacyPayload = JsonDocument.Parse(legacyPayloadJson);
if (legacyPayload.RootElement.GetProperty("coordinateFrame").ValueKind != JsonValueKind.Null
    || legacyPayload.RootElement.GetProperty("element").GetProperty("metadata").ValueKind != JsonValueKind.Object
    || legacyPayload.RootElement.GetProperty("element").GetProperty("reviewStatus").GetString() != "unreviewed")
    throw new InvalidOperationException("Legacy payload without optional provenance fields was not preserved.");

Console.WriteLine($"{cases.Length} Revit member-section policy checks and 2 provenance serialization checks passed.");
