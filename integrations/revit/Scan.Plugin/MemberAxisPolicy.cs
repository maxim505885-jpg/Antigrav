using System.Text.Json;

namespace Scan.Revit.Plugin;

public static class MemberAxisPolicy
{
    public static bool TryRead(JsonElement geometry, out double[] start, out double[] end)
    {
        start = Array.Empty<double>();
        end = Array.Empty<double>();
        if (geometry.ValueKind != JsonValueKind.Object
            || !TryPoint(geometry, "p0", out start)
            || !TryPoint(geometry, "p1", out end))
            return false;
        var dx = end[0] - start[0];
        var dy = end[1] - start[1];
        var dz = end[2] - start[2];
        return double.IsFinite(dx) && double.IsFinite(dy) && double.IsFinite(dz)
            && Math.Sqrt(dx * dx + dy * dy + dz * dz) > 1e-6;
    }

    private static bool TryPoint(JsonElement geometry, string property, out double[] point)
    {
        point = Array.Empty<double>();
        if (!geometry.TryGetProperty(property, out var value)
            || value.ValueKind != JsonValueKind.Array || value.GetArrayLength() != 3)
            return false;
        point = new double[3];
        for (var i = 0; i < 3; i++)
        {
            if (!value[i].TryGetDouble(out point[i]) || !double.IsFinite(point[i]))
                return false;
        }
        return true;
    }
}
