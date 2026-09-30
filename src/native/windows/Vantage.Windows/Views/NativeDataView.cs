using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Vantage.Core;
namespace Vantage.Windows.Views;

// Native controls keep data selectable and accessible without a web renderer.
public static class NativeDataView
{
    public static bool English { get; set; }
    public static UIElement Create(JsonElement data, string? label = null, int depth = 0)
    {
        var panel = new StackPanel { Spacing = 8 };
        if (!string.IsNullOrEmpty(label)) panel.Children.Add(Label(label, true));
        if (data.ValueKind == JsonValueKind.Array)
        {
            var items = data.EnumerateArray().ToArray();
            if (items.Length == 0) { panel.Children.Add(Label("—")); return panel; }
            if (items.All(x => x.ValueKind == JsonValueKind.Object)) return Table(items, label);
            foreach (var item in items) panel.Children.Add(Create(item, depth: depth + 1));
        }
        else if (data.ValueKind == JsonValueKind.Object)
        {
            foreach (var property in data.EnumerateObject())
            {
                if (property.Value.ValueKind is JsonValueKind.Object or JsonValueKind.Array)
                    panel.Children.Add(new Expander { Header = Pretty(property.Name), Content = depth < 6 ? Create(property.Value, depth: depth + 1) : Label(property.Value.ToString()), HorizontalAlignment = HorizontalAlignment.Stretch, IsExpanded = depth < 1 });
                else panel.Children.Add(Label($"{Pretty(property.Name)}: {property.Value.Text("—")}"));
            }
        }
        else panel.Children.Add(Label(data.Text("—")));
        return panel;
    }
    public static UIElement Table(JsonElement[] rows, string? title = null)
    {
        var panel = new StackPanel { Spacing = 10 };
        if (title is not null) panel.Children.Add(Label(title, true));
        var search = new TextBox { PlaceholderText = English ? "Filter" : "筛选", MaxWidth = 400, HorizontalAlignment = HorizontalAlignment.Left };
        var content = new StackPanel { Spacing = 4 }; var page = 0; const int pageSize = 100;
        var counter = new TextBlock();
        void Render()
        {
            content.Children.Clear();
            var filtered = rows.Where(r => r.ToString().Contains(search.Text, StringComparison.CurrentCultureIgnoreCase)).ToArray();
            page = Math.Clamp(page, 0, Math.Max(0, (filtered.Length - 1) / pageSize));
            var columns = rows.SelectMany(r => r.EnumerateObject().Select(x => x.Name)).Distinct().ToArray();
            Grid Row(string[] values, bool header)
            {
                var grid = new Grid { Padding = new Thickness(6), ColumnSpacing = 14 };
                for (var index = 0; index < columns.Length; index++)
                {
                    grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(190) });
                    var cell = Label(values[index], header); Grid.SetColumn(cell, index); grid.Children.Add(cell);
                }
                return grid;
            }
            content.Children.Add(Row(columns.Select(Pretty).ToArray(), true));
            foreach (var row in filtered.Skip(page * pageSize).Take(pageSize)) content.Children.Add(Row(columns.Select(c => FormatCell(row.Field(c))).ToArray(), false));
            counter.Text = $"{Math.Min(page * pageSize + 1, filtered.Length)}–{Math.Min((page + 1) * pageSize, filtered.Length)} / {filtered.Length}";
        }
        var prev = new Button { Content = "‹" }; prev.Click += (_, _) => { page--; Render(); };
        var next = new Button { Content = "›" }; next.Click += (_, _) => { page++; Render(); };
        var nav = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 12 }; nav.Children.Add(prev); nav.Children.Add(counter); nav.Children.Add(next);
        search.TextChanged += (_, _) => { page = 0; Render(); };
        panel.Children.Add(search); panel.Children.Add(new ScrollViewer { Content = content, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollBarVisibility = ScrollBarVisibility.Disabled }); panel.Children.Add(nav); Render(); return panel;
    }
    static string FormatCell(JsonElement value) => value.ValueKind == JsonValueKind.Array ? string.Join(" · ", value.Items().Select(FormatCell)) : value.ValueKind == JsonValueKind.Object ? string.Join(" · ", value.EnumerateObject().Select(p => $"{Pretty(p.Name)}: {FormatCell(p.Value)}")) : value.Text("—");
    static TextBlock Label(string text, bool heading = false) => new() { Text = text, TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true, FontSize = heading ? 16 : 14, FontWeight = heading ? Microsoft.UI.Text.FontWeights.SemiBold : Microsoft.UI.Text.FontWeights.Normal };
    public static string Pretty(string name) => name.Replace('_', ' ');
}
