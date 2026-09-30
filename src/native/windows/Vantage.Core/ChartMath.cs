using System.Globalization;
using System.Text.Json;
namespace Vantage.Core;
public sealed record ChartPoint(double X, double? Y, string Label);
public static class ChartMath
{
    public static ChartPoint[] ExtractPoints(JsonElement series, JsonElement xAxis)
    {
        if (xAxis.ValueKind == JsonValueKind.Array) xAxis = xAxis.Items().FirstOrDefault();
        var labels = xAxis.Field("data").Items().Select(x => x.Text()).ToArray();
        var time = xAxis.Field("type").Text() == "time"; var valueAxis = xAxis.Field("type").Text() == "value";
        return series.Field("data").Items().Select((raw, i) =>
        {
            var value = raw.ValueKind == JsonValueKind.Object ? raw.Field("value") : raw;
            var pair = value.Items().ToArray();
            var label = pair.Length > 1 ? pair[0].Text() : i < labels.Length ? labels[i] : i.ToString(CultureInfo.InvariantCulture);
            var y = pair.Length > 1 ? pair[^1].Number() : value.Number(); double x = i;
            if (pair.Length > 1 && (time || valueAxis)) x = pair[0].Number() ?? (time && DateTimeOffset.TryParse(label, CultureInfo.InvariantCulture, DateTimeStyles.AssumeLocal, out var parsed) ? parsed.ToUnixTimeMilliseconds() : i);
            return new ChartPoint(x, y, label);
        }).ToArray();
    }
    public static double YRatio(double value, double min, double max, bool inverse = false)
    { if (max <= min) max = min + 1; var normalized = (value - min) / (max - min); return inverse ? normalized : 1 - normalized; }
    public static (double min, double max) SignedStackExtent(IEnumerable<IEnumerable<ChartPoint>> series)
    {
        var groups = series.SelectMany(x => x).Where(x => x.Y.HasValue).GroupBy(x => x.X); double min = 0, max = 0;
        foreach (var group in groups) { min = Math.Min(min, group.Where(x => x.Y < 0).Sum(x => x.Y!.Value)); max = Math.Max(max, group.Where(x => x.Y >= 0).Sum(x => x.Y!.Value)); }
        return (min, max);
    }
    public static double GroupedBarOffset(int index, int count, double slotWidth) => (index - (count - 1) / 2.0) * (slotWidth / Math.Max(1, count));
}
