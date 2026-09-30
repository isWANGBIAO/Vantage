using Vantage.Core;
using Xunit;
namespace Vantage.Core.Tests;
public class ChartTests
{
    [Fact] public void KeepsNullGapsAndIrregularTimeSpacing()
    {
        var option = JsonData.ChartElement(new { xAxis = new { type = "time" }, series = new { data = new object?[][] { ["2026-01-01", 10], ["2026-01-03", null], ["2026-01-10", 30] } } });
        Assert.Equal("time", option.Field("xAxis").Field("type").Text());
        var points = ChartMath.ExtractPoints(option.Field("series"), option.Field("xAxis"));
        Assert.Null(points[1].Y); Assert.Equal(4.5, (points[2].X - points[0].X) / (points[1].X - points[0].X));
    }
    [Fact] public void ObjectDatumValuePreservesPairs()
    {
        var series = JsonData.Element(new { data = new[] { new { value = new object[] { "2026-01-01", 42 } } } });
        Assert.Equal(42, ChartMath.ExtractPoints(series, JsonData.Element(new { type = "time" }))[0].Y);
    }
    [Fact] public void CategoryLabelsAlignWithScalarData()
    {
        var points = ChartMath.ExtractPoints(JsonData.Element(new { data = new double?[] { 10, null, 20 } }), JsonData.Element(new { type = "category", data = new[] { "Mon", "Tue", "Wed" } }));
        Assert.Equal("Wed", points[2].Label); Assert.Equal(2, points[2].X);
    }
    [Fact] public void InversePaceAxisMovesSmallerValuesUp() { Assert.True(ChartMath.YRatio(4, 0, 10, true) < ChartMath.YRatio(8, 0, 10, true)); }
    [Fact] public void NormalAxisMovesLargerValuesUp() { Assert.True(ChartMath.YRatio(8, 0, 10) < ChartMath.YRatio(4, 0, 10)); }
    [Fact] public void PositiveAndNegativeStacksDoNotCancel()
    {
        var extent = ChartMath.SignedStackExtent(new[] { new[] { new ChartPoint(0, 10, "a"), new ChartPoint(1, -5, "b") }, new[] { new ChartPoint(0, -8, "a"), new ChartPoint(1, -10, "b") } });
        Assert.Equal(-15, extent.min); Assert.Equal(10, extent.max);
    }
    [Fact] public void LocalizedChartsKeepNumericData()
    {
        var value = PlotText.Localize(JsonData.Element(new { name = "体重", value = 65.2 }), true);
        Assert.Equal("Weight", value.Field("name").Text()); Assert.Equal(65.2, value.Field("value").Number());
    }
    [Fact] public void RadarLegendLabelsEveryDatumWithStablePaletteIndices()
    {
        var option = JsonData.ChartElement(new { series = new[] { new { name = "Activity", type = "radar", data = new[] { new { name = "Today", value = new[] { 70, 40, 80 } }, new { name = "Goal", value = new[] { 80, 60, 90 } } } } } });
        var entries = ChartMath.RadarLegend(option);
        Assert.Equal(new[] { "Today", "Goal" }, entries.Select(x => x.Label));
        Assert.Equal(new[] { 0, 1 }, entries.Select(x => x.ColorIndex));
        Assert.Equal(new[] { 0, 1 }, entries.Select(x => x.DatumIndex));
        Assert.All(entries, x => Assert.Equal(0, x.SeriesIndex));
    }
    [Fact] public void HidingAnotherRadarSeriesDoesNotRenumberColors()
    {
        var option = JsonData.ChartElement(new { series = new[] { new { name = "First", type = "radar", data = new[] { new { name = "A", value = new[] { 1, 2, 3 } } } }, new { name = "Second", type = "radar", data = new[] { new { name = "B", value = new[] { 3, 2, 1 } } } } } });
        var visible = ChartMath.RadarLegend(option).Where(x => x.SeriesIndex != 0).ToArray();
        Assert.Single(visible); Assert.Equal("B", visible[0].Label); Assert.Equal(1, visible[0].ColorIndex);
    }
    [Theory]
    [InlineData(false, 20, 0)]
    [InlineData(true, 0, 20)]
    public void AxisTicksMatchPlotProjection(bool inverse, double top, double bottom)
    {
        Assert.Equal(top, ChartMath.AxisTickValue(0, 20, 0, inverse));
        Assert.Equal(bottom, ChartMath.AxisTickValue(0, 20, 1, inverse));
        Assert.Equal(10, ChartMath.AxisTickValue(0, 20, .5, inverse));
        Assert.Equal(0, ChartMath.YRatio(top, 0, 20, inverse));
        Assert.Equal(1, ChartMath.YRatio(bottom, 0, 20, inverse));
    }
    [Fact] public void GroupedBarsDoNotOverlay() { Assert.Equal(-20, ChartMath.GroupedBarOffset(0, 2, 80)); Assert.Equal(20, ChartMath.GroupedBarOffset(1, 2, 80)); }
}
