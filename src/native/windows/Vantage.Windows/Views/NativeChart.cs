using System.Text.Json;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;
using Vantage.Core;
using Windows.Foundation;
using Windows.UI;
namespace Vantage.Windows.Views;

// The backend's ECharts JSON is a data contract; rendering is native XAML geometry.
public sealed class NativeChart : StackPanel
{
    static readonly Color[] Palette = [Color.FromArgb(255, 16, 185, 129), Color.FromArgb(255, 56, 189, 248), Color.FromArgb(255, 245, 158, 11), Color.FromArgb(255, 167, 139, 250), Color.FromArgb(255, 244, 114, 182), Color.FromArgb(255, 45, 212, 191)];
    readonly JsonElement option;
    readonly Canvas canvas = new() { Height = 340, MinWidth = 300 };
    readonly HashSet<int> hidden = [];
    readonly Slider start = new() { Header = "起点 / Start %", Minimum = 0, Maximum = 99, Value = 0, MinWidth = 180 };
    readonly Slider end = new() { Header = "终点 / End %", Minimum = 1, Maximum = 100, Value = 100, MinWidth = 180 };
    readonly JsonElement[] series;
    readonly RadarLegendEntry[] radarLegend;
    public NativeChart(JsonElement option, bool english = false)
    {
        start.Header = english ? "Start %" : "起点 %"; end.Header = english ? "End %" : "终点 %";
        this.option = option; series = option.Field("series").Items().ToArray(); radarLegend = ChartMath.RadarLegend(option); Spacing = 10;
        var legend = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 14 };
        for (var index = 0; index < series.Length; index++)
        {
            var id = index; var checkbox = new CheckBox { Content = series[index].Field("name").Text($"Series {index + 1}"), IsChecked = true, Foreground = Brush(index) };
            checkbox.Checked += (_, _) => { hidden.Remove(id); Draw(); }; checkbox.Unchecked += (_, _) => { hidden.Add(id); Draw(); }; legend.Children.Add(checkbox);
        }
        Children.Add(new ScrollViewer { Content = legend, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollBarVisibility = ScrollBarVisibility.Disabled });
        if (radarLegend.Length > 0)
        {
            var names = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 18 };
            foreach (var entry in radarLegend)
            {
                var name = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6 };
                name.Children.Add(new Rectangle { Width = 12, Height = 12, Fill = Brush(entry.ColorIndex), VerticalAlignment = VerticalAlignment.Center });
                name.Children.Add(new TextBlock { Text = entry.Label, Foreground = Brush(entry.ColorIndex), VerticalAlignment = VerticalAlignment.Center }); names.Children.Add(name);
            }
            Children.Add(new ScrollViewer { Content = names, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollBarVisibility = ScrollBarVisibility.Disabled });
        }
        Children.Add(canvas);
        var controls = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 16 }; controls.Children.Add(start); controls.Children.Add(end); Children.Add(controls);
        start.ValueChanged += (_, _) => Draw(); end.ValueChanged += (_, _) => Draw();
        canvas.SizeChanged += (_, _) => Draw(); Loaded += (_, _) => Draw();
        var rows = new List<Dictionary<string, object?>>();
        foreach (var s in series) foreach (var point in s.Field("data").Items()) rows.Add(new() { ["Series"] = s.Field("name").Text(), ["Value"] = point });
        Children.Add(new Expander { Header = english ? "Data values" : "数据明细", Content = NativeDataView.Create(JsonData.Element(rows)), HorizontalAlignment = HorizontalAlignment.Stretch });
    }
    static SolidColorBrush Brush(int index) => new(Palette[index % Palette.Length]);
    void Draw()
    {
        if (canvas.ActualWidth < 10) return;
        canvas.Children.Clear();
        if (series.Any(s => s.Field("type").Text() == "radar")) { DrawRadar(); return; }
        if (series.Any(s => s.Field("type").Text() == "pie")) { DrawPie(); return; }
        DrawCartesian();
    }
    ChartPoint[] Points(JsonElement s) => ChartMath.ExtractPoints(s, option.Field("xAxis"));
    void DrawCartesian()
    {
        const double left = 65, top = 20, bottom = 42;
        var active = series.Select((s, i) => (s, i, points: Points(s))).Where(x => !hidden.Contains(x.i)).ToArray();
        var extraAxes = active.Select(x => (int)(x.s.Field("yAxisIndex").Number() ?? 0)).Where(x => x != 0).Distinct().Order().ToArray();
        var width = Math.Max(100, canvas.ActualWidth - left - 80 - Math.Max(0, extraAxes.Length - 1) * 80); var height = canvas.Height - top - bottom;
        var all = active.SelectMany(x => x.points).ToArray(); if (all.Length == 0) { Label("暂无数据 / No data", left, top); return; }
        var minX = all.Min(p => p.X); var maxX = all.Max(p => p.X);
        if (active.Any(x => x.s.Field("type").Text() == "bar")) { var xs = all.Select(p => p.X).Distinct().Order().ToArray(); var pad = xs.Length > 1 ? (xs[1] - xs[0]) / 2 : .5; minX -= pad; maxX += pad; }
        if (minX == maxX) maxX++;
        var lowX = minX + (maxX - minX) * Math.Min(start.Value, end.Value - 1) / 100; var highX = minX + (maxX - minX) * Math.Max(end.Value, start.Value + 1) / 100;
        var axes = option.Field("yAxis"); var axisArray = axes.ValueKind == JsonValueKind.Array ? axes.Items().ToArray() : new[] { axes };
        var ranges = new Dictionary<int, (double min, double max)>();
        foreach (var group in active.GroupBy(x => (int)(x.s.Field("yAxisIndex").Number() ?? 0)))
        {
            var values = group.SelectMany(x => x.points).Where(x => x.Y.HasValue && x.X >= lowX && x.X <= highX).Select(p => p.Y!.Value).ToList();
            if (values.Count == 0) values.Add(0);
            // Stacked bars share one cumulative axis; the data table retains every original value.
            foreach (var stack in group.Where(x => x.s.Field("stack").Text() != "").GroupBy(x => x.s.Field("stack").Text()))
            {
                var extent = ChartMath.SignedStackExtent(stack.Select(x => x.points.Where(p => p.X >= lowX && p.X <= highX)));
                values.Add(extent.min); values.Add(extent.max);
            }
            var axis = group.Key < axisArray.Length ? axisArray[group.Key] : default;
            var min = axis.Field("min").Number() ?? (group.Any(x => x.s.Field("type").Text() == "bar") ? Math.Min(0, values.Min()) : values.Min());
            var max = axis.Field("max").Number() ?? values.Max(); if (min == max) max = min + 1;
            ranges[group.Key] = (min, max);
            var titleX = group.Key == 0 ? left : left + width + 8 + Array.IndexOf(extraAxes, group.Key) * 80;
            Label(axis.Field("name").Text($"Y{group.Key + 1}"), titleX, top - 20, Brush(group.First().i));
        }
        double X(double x) => left + (x - lowX) / (highX - lowX) * width;
        double Y(double y, int axis) { var (min, max) = ranges[axis]; var inverse = axis < axisArray.Length && axisArray[axis].Field("inverse").ValueKind == JsonValueKind.True; return top + ChartMath.YRatio(y, min, max, inverse) * height; }
        for (var k = 0; k <= 4; k++)
        {
            var y = top + height * k / 4; Line(left, y, left + width, y, new SolidColorBrush(Color.FromArgb(50, 128, 128, 128)), 1);
            foreach (var (axisIndex, range) in ranges)
            {
                var axis = axisIndex < axisArray.Length ? axisArray[axisIndex] : default;
                var tick = ChartMath.AxisTickValue(range.min, range.max, k / 4.0, axis.Field("inverse").ValueKind == JsonValueKind.True);
                var number = tick.ToString("0.##"); var format = axis.Field("axisLabel").Field("formatter").Text();
                var text = format.Contains("{value}", StringComparison.Ordinal) ? format.Replace("{value}", number, StringComparison.Ordinal) : number;
                var x = axisIndex == 0 ? 0 : left + width + 8 + Array.IndexOf(extraAxes, axisIndex) * 80;
                var color = Brush(active.First(a => (int)(a.s.Field("yAxisIndex").Number() ?? 0) == axisIndex).i);
                Label(text, x, y - 8, color);
            }
        }
        var stacks = new Dictionary<(int, string, double, bool), double>();
        string BarGroup(JsonElement s, int index) => s.Field("stack").Text() is { Length: > 0 } stack ? $"{s.Field("yAxisIndex").Number() ?? 0}:{stack}" : $"series-{index}";
        var barGroups = active.Where(x => x.s.Field("type").Text() == "bar").Select(x => BarGroup(x.s, x.i)).Distinct().ToArray();
        foreach (var (s, index, points) in active)
        {
            var axis = (int)(s.Field("yAxisIndex").Number() ?? 0); var type = s.Field("type").Text("line"); var stack = s.Field("stack").Text();
            Point? previous = null;
            foreach (var point in points.Where(p => p.X >= lowX && p.X <= highX))
            {
                if (!point.Y.HasValue) { previous = null; continue; }
                var x = X(point.X); var value = point.Y.Value; var y = Y(value, axis); Shape shape;
                if (type == "bar")
                {
                    var stackKey = (axis, stack, point.X, value >= 0); var before = stack.Length > 0 ? stacks.GetValueOrDefault(stackKey) : 0; var after = before + value;
                    if (stack.Length > 0) stacks[stackKey] = after;
                    var y0 = Y(before, axis); var y1 = Y(after, axis); var slotWidth = width / Math.Max(1, points.Count(p => p.X >= lowX && p.X <= highX)) * .72; var barWidth = Math.Max(2, slotWidth / Math.Max(1, barGroups.Length));
                    x += ChartMath.GroupedBarOffset(Array.IndexOf(barGroups, BarGroup(s, index)), barGroups.Length, slotWidth);
                    shape = new Rectangle { Width = barWidth, Height = Math.Max(1, Math.Abs(y0 - y1)), Fill = Brush(index) }; Canvas.SetLeft(shape, x - barWidth / 2); Canvas.SetTop(shape, Math.Min(y0, y1));
                }
                else
                {
                    if (type != "scatter" && previous.HasValue) Line(previous.Value.X, previous.Value.Y, x, y, Brush(index), 2);
                    shape = new Ellipse { Width = type == "scatter" ? 8 : 5, Height = type == "scatter" ? 8 : 5, Fill = Brush(index) }; Canvas.SetLeft(shape, x - 3); Canvas.SetTop(shape, y - 3); previous = new Point(x, y);
                }
                ToolTipService.SetToolTip(shape, $"{s.Field("name").Text()}\n{point.Label}: {value:0.####} {(axis < axisArray.Length ? axisArray[axis].Field("name").Text() : "")}"); canvas.Children.Add(shape);
            }
        }
        var visible = all.Where(x => x.X >= lowX && x.X <= highX).OrderBy(x => x.X).ToArray();
        if (visible.Length > 0) { Label(visible[0].Label, left, top + height + 10); Label(visible[^1].Label, left + width - 100, top + height + 10); }
    }
    void DrawRadar()
    {
        var indicators = option.Field("radar").Field("indicator").Items().ToArray(); if (indicators.Length < 3) { Label("No radar indicators", 10, 10); return; }
        var cx = canvas.ActualWidth / 2; var cy = canvas.Height / 2; var radius = Math.Min(canvas.ActualWidth / 2 - 100, 120);
        Point At(int i, double r) { var angle = 2 * Math.PI * i / indicators.Length - Math.PI / 2; return new Point(cx + Math.Cos(angle) * r, cy + Math.Sin(angle) * r); }
        for (var ring = 1; ring <= 4; ring++)
        {
            var polygon = new Polygon { Stroke = new SolidColorBrush(Color.FromArgb(90, 128, 128, 128)), StrokeThickness = 1 };
            for (var i = 0; i < indicators.Length; i++) polygon.Points.Add(At(i, radius * ring / 4)); canvas.Children.Add(polygon);
        }
        for (var i = 0; i < indicators.Length; i++) { var p = At(i, radius + 22); Label(indicators[i].Field("name").Text(), p.X - 35, p.Y - 8); }
        foreach (var entry in radarLegend)
        {
            if (hidden.Contains(entry.SeriesIndex)) continue;
            var row = series[entry.SeriesIndex].Field("data").Items().ElementAt(entry.DatumIndex);
            var values = row.Field("value").Items().Select(x => x.Number() ?? 0).ToArray(); var color = entry.ColorIndex;
            var polygon = new Polygon { Stroke = Brush(color), StrokeThickness = 2, Fill = new SolidColorBrush(Color.FromArgb(35, Palette[color % Palette.Length].R, Palette[color % Palette.Length].G, Palette[color % Palette.Length].B)) };
            for (var i = 0; i < indicators.Length; i++) polygon.Points.Add(At(i, radius * Math.Clamp((i < values.Length ? values[i] : 0) / Math.Max(1, indicators[i].Field("max").Number() ?? 100), 0, 1)));
            ToolTipService.SetToolTip(polygon, entry.Label + ": " + string.Join(", ", values)); canvas.Children.Add(polygon);
        }
    }
    void DrawPie()
    {
        var values = series.SelectMany((s, i) => hidden.Contains(i) ? [] : s.Field("data").Items()).ToArray(); var total = values.Sum(v => Math.Max(0, v.Field("value").Number() ?? 0));
        if (total <= 0) return; double angle = -Math.PI / 2; var radius = 130.0; var center = new Point(canvas.ActualWidth / 2, 165);
        for (var i = 0; i < values.Length; i++)
        {
            var value = Math.Max(0, values[i].Field("value").Number() ?? 0); var sweep = value / total * Math.PI * 2;
            var poly = new Polygon { Fill = Brush(i) }; poly.Points.Add(center);
            for (var step = 0; step <= 60; step++) { var a = angle + sweep * step / 60; poly.Points.Add(new Point(center.X + Math.Cos(a) * radius, center.Y + Math.Sin(a) * radius)); }
            angle += sweep; ToolTipService.SetToolTip(poly, $"{values[i].Field("name").Text()}: {value} ({value / total:P1})"); canvas.Children.Add(poly);
        }
    }
    void Line(double x1, double y1, double x2, double y2, Brush brush, double width) => canvas.Children.Add(new Line { X1 = x1, Y1 = y1, X2 = x2, Y2 = y2, Stroke = brush, StrokeThickness = width });
    void Label(string text, double x, double y, Brush? foreground = null) { var label = new TextBlock { Text = text, FontSize = 11 }; if (foreground is not null) label.Foreground = foreground; Canvas.SetLeft(label, x); Canvas.SetTop(label, y); canvas.Children.Add(label); }
}
