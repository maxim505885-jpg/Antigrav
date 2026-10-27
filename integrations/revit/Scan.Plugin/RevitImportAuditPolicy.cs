using System.Text.Json;

namespace Scan.Revit.Plugin;

public static class RevitImportAuditPolicy
{
    public static bool IsExpectedToImport(JsonElement element)
    {
        if (!element.TryGetProperty("class_name", out var classValue)
            || classValue.ValueKind != JsonValueKind.String
            || !element.TryGetProperty("geometry", out var geometry)
            || geometry.ValueKind != JsonValueKind.Object
            || !geometry.TryGetProperty("kind", out var kindValue)
            || kindValue.ValueKind != JsonValueKind.String)
            return false;

        var className = classValue.GetString();
        var kind = kindValue.GetString();
        if (className == "truss")
            return false; // Revit importer intentionally skips unverified truss envelopes.
        if (kind == "oriented_box")
            return true;
        if (kind == "member")
            return MemberAxisPolicy.TryRead(geometry, out _, out _);
        return className == "slab" && kind == "slab"
            && SlabGeometryPolicy.TryRead(geometry, out _, out _, out _);
    }
}
