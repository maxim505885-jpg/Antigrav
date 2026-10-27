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

var auditCases = new (string Json, bool Expected)[]
{
    ("{\"class_name\":\"column\",\"geometry\":{\"kind\":\"oriented_box\"}}", true),
    ("{\"class_name\":\"truss\",\"geometry\":{\"kind\":\"member\",\"p0\":[0,0,0],\"p1\":[1,0,0]}}", false),
    ("{\"class_name\":\"beam\",\"geometry\":{\"kind\":\"member\",\"p0\":[0,0,0],\"p1\":[1,0,0]}}", true),
    ("{\"class_name\":\"beam\",\"geometry\":{\"kind\":\"member\",\"p0\":[0,0,0],\"p1\":[0,0,0]}}", false),
    ("{\"class_name\":\"slab\",\"geometry\":{\"kind\":\"slab\",\"polygon\":[[0,0],[2,0],[2,1],[0,1]]}}", true),
    ("{\"class_name\":\"slab\",\"geometry\":{\"kind\":\"slab\",\"polygon\":[[0,0],[1,0],[0,0]]}}", false),
};
foreach (var (json, expected) in auditCases)
{
    using var document = JsonDocument.Parse(json);
    var importable = RevitImportAuditPolicy.IsExpectedToImport(document.RootElement);
    if (importable != expected)
        throw new InvalidOperationException($"Revit audit inclusion policy mismatch for {json}: importable={importable}");
}
Console.WriteLine($"{auditCases.Length} Revit post-import audit inclusion checks passed.");

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

var axisCases = new (string Json, bool Expected)[]
{
    ("{\"kind\":\"member\",\"p0\":[0,0,0],\"p1\":[5,0,2]}", true),
    ("{\"kind\":\"member\",\"p0\":[0,0,0],\"p1\":[0,0,0]}", false),
    ("{\"kind\":\"member\",\"p0\":[0,0,0],\"p1\":[1,0]}", false),
    ("{\"kind\":\"member\",\"p0\":[0,0,0],\"p1\":[1e999,0,0]}", false),
};
foreach (var (json, expected) in axisCases)
{
    using var document = JsonDocument.Parse(json);
    var supported = MemberAxisPolicy.TryRead(document.RootElement, out _, out _);
    if (supported != expected)
        throw new InvalidOperationException($"Member axis policy mismatch for {json}: supported={supported}");
}
Console.WriteLine($"{axisCases.Length} Revit member axis policy checks passed.");

var slabCases = new (string Json, bool Expected, int VertexCount, double BaseZ, double Thickness)[]
{
    ("{\"kind\":\"slab\",\"polygon\":[[0,0],[4,0],[4,3],[0,3]],\"z\":2,\"assumed_thickness\":0.3}", true, 4, 2, 0.3),
    ("{\"kind\":\"slab\",\"polygon\":[[0,3],[4,3],[4,0],[0,0]],\"z\":0}", true, 4, 0, 0.2),
    ("{\"kind\":\"slab\",\"polygon\":[[0,0],[4,0],[4,3],[0,3],[0,0]]}", true, 4, 0, 0.2),
    ("{\"kind\":\"slab\",\"polygon\":[[0,0],[4,0],[4,3],[0,3]],\"assumed_thickness\":0.001}", true, 4, 0, 0.02),
    ("{\"kind\":\"slab\",\"polygon\":[[0,0],[1,1],[2,2]]}", false, 0, 0, 0),
    ("{\"kind\":\"slab\",\"polygon\":[[0,0],[1,0],[0,0]]}", false, 0, 0, 0),
    ("{\"kind\":\"slab\",\"polygon\":[[0,0],[1,0],[0,1]],\"assumed_thickness\":-0.1}", false, 0, 0, 0),
    ("{\"kind\":\"slab\",\"polygon\":[[0,0],[1,0],[0,1]],\"z\":1e999}", false, 0, 0, 0),
};
foreach (var (json, expected, vertexCount, expectedZ, expectedThickness) in slabCases)
{
    using var document = JsonDocument.Parse(json);
    var supported = SlabGeometryPolicy.TryRead(document.RootElement, out var polygon, out var z, out var thickness);
    if (supported != expected || (supported && (polygon.Count != vertexCount
        || Math.Abs(z - expectedZ) > 1e-12 || Math.Abs(thickness - expectedThickness) > 1e-12)))
        throw new InvalidOperationException($"Slab geometry policy mismatch for {json}: supported={supported}, vertices={polygon.Count}, z={z}, thickness={thickness}");
}
Console.WriteLine($"{slabCases.Length} Revit slab geometry policy checks passed.");

if (args.Length > 0)
{
    using var liveDocument = JsonDocument.Parse(File.ReadAllText(args[0]));
    var liveSlabCount = 0;
    var liveMemberCount = 0;
    var liveAxisOnlyCount = 0;
    var auditExpectedImportCount = 0;
    var auditIntentionallySkippedCount = 0;
    foreach (var item in liveDocument.RootElement.GetProperty("elements").EnumerateArray())
    {
        if (RevitImportAuditPolicy.IsExpectedToImport(item))
            auditExpectedImportCount++;
        else
            auditIntentionallySkippedCount++;
        var geometry = item.GetProperty("geometry");
        var id = item.GetProperty("id").GetString();
        if (item.GetProperty("class_name").GetString() == "slab")
        {
            if (!SlabGeometryPolicy.TryRead(geometry, out var polygon, out _, out _))
                throw new InvalidOperationException($"Live slab {id} failed Revit geometry policy.");
            if (polygon.Count < 3)
                throw new InvalidOperationException($"Live slab {id} returned fewer than three vertices.");
            liveSlabCount++;
        }
        if (geometry.TryGetProperty("kind", out var kind) && kind.GetString() == "member")
        {
            if (!MemberAxisPolicy.TryRead(geometry, out _, out _))
                throw new InvalidOperationException($"Live member {id} failed Revit axis policy.");
            liveMemberCount++;
            if (!MemberSectionPolicy.TryGetPositiveSectionMetres(geometry, out _))
                liveAxisOnlyCount++;
        }
    }
    if (liveSlabCount == 0 || liveMemberCount == 0)
        throw new InvalidOperationException("The live BIM snapshot did not contain both slabs and linear members to validate.");
    Console.WriteLine($"{liveSlabCount} live BIM slab geometries passed policy; {liveMemberCount} member axes passed policy, {liveAxisOnlyCount} have unknown sections and will be axis-only.");
    Console.WriteLine($"Post-reopen audit expects {auditExpectedImportCount} imported IDs and lists {auditIntentionallySkippedCount} intentionally skipped source IDs.");
}
