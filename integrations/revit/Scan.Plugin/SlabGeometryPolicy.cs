using System.Text.Json;

namespace Scan.Revit.Plugin;

public static class SlabGeometryPolicy
{
    public static bool TryRead(JsonElement geometry, out IReadOnlyList<(double X, double Y)> polygon,
        out double baseElevationMetres, out double thicknessMetres)
    {
        polygon = Array.Empty<(double X, double Y)>();
        baseElevationMetres = 0;
        thicknessMetres = 0;
        if (!geometry.TryGetProperty("polygon", out var points) || points.ValueKind != JsonValueKind.Array)
            return false;

        var parsed = new List<(double X, double Y)>();
        foreach (var point in points.EnumerateArray())
        {
            if (point.ValueKind != JsonValueKind.Array || point.GetArrayLength() < 2
                || !point[0].TryGetDouble(out var x) || !double.IsFinite(x)
                || !point[1].TryGetDouble(out var y) || !double.IsFinite(y))
                return false;
            var xy = (x, y);
            // Collapse consecutive duplicate vertices; degenerate contours are
            // rejected by the vertex and area checks below.
            if (parsed.Count == 0 || parsed[^1] != xy)
                parsed.Add(xy);
        }
        if (parsed.Count > 1 && parsed[0] == parsed[^1])
            parsed.RemoveAt(parsed.Count - 1);
        if (parsed.Count < 3)
            return false;

        var areaTwice = 0.0;
        for (var i = 0; i < parsed.Count; i++)
        {
            var current = parsed[i];
            var next = parsed[(i + 1) % parsed.Count];
            var dx = next.X - current.X;
            var dy = next.Y - current.Y;
            if (Math.Sqrt(dx * dx + dy * dy) < 1e-9)
                return false;
            areaTwice += current.X * next.Y - next.X * current.Y;
        }
        if (!double.IsFinite(areaTwice) || Math.Abs(areaTwice) <= 1e-12)
            return false;

        var elevation = geometry.TryGetProperty("z", out var zValue) ? zValue : default;
        baseElevationMetres = elevation.ValueKind == JsonValueKind.Number && elevation.TryGetDouble(out var z) && double.IsFinite(z)
            ? z : elevation.ValueKind == JsonValueKind.Undefined ? 0 : double.NaN;
        var thickness = geometry.TryGetProperty("assumed_thickness", out var thicknessValue) ? thicknessValue : default;
        thicknessMetres = thickness.ValueKind == JsonValueKind.Number && thickness.TryGetDouble(out var supplied) && double.IsFinite(supplied)
            ? supplied : thickness.ValueKind == JsonValueKind.Undefined ? 0.2 : double.NaN;
        if (!double.IsFinite(baseElevationMetres) || !double.IsFinite(thicknessMetres) || thicknessMetres <= 0)
            return false;

        // The BIM/IFC exporter guarantees at least 20 mm extrusion depth.
        thicknessMetres = Math.Max(0.02, thicknessMetres);
        if (areaTwice < 0)
            parsed.Reverse();
        polygon = parsed;
        return true;
    }
}
