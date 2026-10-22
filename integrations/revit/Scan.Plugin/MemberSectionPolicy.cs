using System.Text.Json;

namespace Scan.Revit.Plugin;

internal static class MemberSectionPolicy
{
    public static bool TryGetPositiveSectionMetres(JsonElement geometry, out double sectionMetres)
    {
        sectionMetres = 0;
        return geometry.ValueKind == JsonValueKind.Object
            && geometry.TryGetProperty("section_m", out var value)
            && value.ValueKind == JsonValueKind.Number
            && value.TryGetDouble(out sectionMetres)
            && double.IsFinite(sectionMetres)
            && sectionMetres > 0;
    }
}
