using System.Text.RegularExpressions;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Documents;
using Microsoft.UI.Xaml.Media;
namespace Vantage.Windows.Views;

public static class MarkdownView
{
    // A native, selectable Markdown presentation. HTML, scripts and automatic remote image loads are not interpreted.
    static readonly Regex InlinePattern = new(@"(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?://[^\s)]+\)|\*[^*]+\*)", RegexOptions.Compiled, TimeSpan.FromMilliseconds(100));
    static readonly Regex LinkPattern = new(@"^\[([^\]]+)\]\((https?://[^\s)]+)\)$", RegexOptions.Compiled, TimeSpan.FromMilliseconds(100));
    static readonly Regex TableRule = new(@"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", RegexOptions.Compiled, TimeSpan.FromMilliseconds(100));
    public static StackPanel Create(string markdown)
    {
        var panel = new StackPanel { Spacing = 9 }; var lines = markdown.Replace("\r", "").Split('\n');
        for (var index = 0; index < lines.Length; index++)
        {
            var line = lines[index];
            if (index >= 5000)
            {
                panel.Children.Add(new Expander { Header = "其余正文 / Remaining text", Content = new TextBox { Text = string.Join("\n", lines.Skip(index)), IsReadOnly = true, AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, MaxHeight = 600 }, HorizontalAlignment = HorizontalAlignment.Stretch }); break;
            }
            if (line.StartsWith("```", StringComparison.Ordinal))
            {
                var code = new List<string>(); while (++index < lines.Length && !lines[index].StartsWith("```", StringComparison.Ordinal)) code.Add(lines[index]);
                panel.Children.Add(new Border { Padding = new Thickness(12), CornerRadius = new CornerRadius(6), BorderThickness = new Thickness(1), BorderBrush = (Brush)Application.Current.Resources["CardStrokeColorDefaultBrush"], Child = new ScrollViewer { HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollBarVisibility = ScrollBarVisibility.Disabled, Content = new TextBlock { Text = string.Join("\n", code), FontFamily = new FontFamily("Consolas"), IsTextSelectionEnabled = true, FontSize = 13 } } }); continue;
            }
            if (index + 1 < lines.Length && line.Contains('|') && TableRule.IsMatch(lines[index + 1]))
            {
                var rows = new List<string[]> { Cells(line) }; index += 2;
                while (index < lines.Length && lines[index].Contains('|') && !string.IsNullOrWhiteSpace(lines[index])) { rows.Add(Cells(lines[index])); index++; }
                index--; panel.Children.Add(Table(rows)); continue;
            }
            if (line.Trim() is "---" or "***" or "___") { panel.Children.Add(new Border { Height = 1, Background = (Brush)Application.Current.Resources["CardStrokeColorDefaultBrush"] }); continue; }
            var level = line.TakeWhile(x => x == '#').Count(); var heading = level > 0 && level < 7 && line.Length > level && line[level] == ' ';
            var value = heading ? line[level..].TrimStart() : line;
            var indent = line.TakeWhile(char.IsWhiteSpace).Count(); var trimmed = value.TrimStart();
            if (trimmed.StartsWith("- [ ] ")) value = "☐ " + trimmed[6..];
            else if (trimmed.StartsWith("- [x] ", StringComparison.OrdinalIgnoreCase)) value = "☑ " + trimmed[6..];
            else if (trimmed.StartsWith("- ") || trimmed.StartsWith("* ")) value = "• " + trimmed[2..];
            else if (trimmed.StartsWith("> ")) value = trimmed[2..];
            var block = InlineText(value); block.FontSize = heading ? Math.Max(16, 27 - level * 2) : 14;
            if (heading) block.FontWeight = Microsoft.UI.Text.FontWeights.SemiBold;
            if (indent > 0) block.Margin = new Thickness(Math.Min(48, indent * 4), 0, 0, 0);
            panel.Children.Add(block);
        }
        return panel;
    }
    static TextBlock InlineText(string value)
    {
        var block = new TextBlock { TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true };
        var cursor = 0;
        try
        {
            foreach (Match match in InlinePattern.Matches(value))
            {
                if (match.Index > cursor) block.Inlines.Add(new Run { Text = value[cursor..match.Index] });
                var text = match.Value; var link = LinkPattern.Match(text);
                if (link.Success && Uri.TryCreate(link.Groups[2].Value, UriKind.Absolute, out var target) && target.Scheme is "http" or "https")
                {
                    var hyperlink = new Hyperlink { NavigateUri = target }; hyperlink.Inlines.Add(new Run { Text = link.Groups[1].Value }); block.Inlines.Add(hyperlink);
                }
                else if (text.StartsWith("**")) { var bold = new Bold(); bold.Inlines.Add(new Run { Text = text[2..^2] }); block.Inlines.Add(bold); }
                else if (text.StartsWith('`')) block.Inlines.Add(new Run { Text = text[1..^1], FontFamily = new FontFamily("Consolas") });
                else if (text.StartsWith('*')) { var italic = new Italic(); italic.Inlines.Add(new Run { Text = text[1..^1] }); block.Inlines.Add(italic); }
                else block.Inlines.Add(new Run { Text = text }); cursor = match.Index + match.Length;
            }
        }
        catch (RegexMatchTimeoutException) { block.Inlines.Clear(); cursor = 0; }
        if (cursor < value.Length) block.Inlines.Add(new Run { Text = value[cursor..] });
        return block;
    }
    static string[] Cells(string value) => value.Trim().Trim('|').Split('|').Select(x => x.Trim()).ToArray();
    static UIElement Table(List<string[]> rows)
    {
        var grid = new Grid { RowSpacing = 6, ColumnSpacing = 14, Padding = new Thickness(8) }; var count = rows.Max(x => x.Length);
        for (var i = 0; i < count; i++) grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(210) });
        for (var row = 0; row < rows.Count; row++)
        {
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            for (var col = 0; col < rows[row].Length; col++) { var cell = InlineText(rows[row][col]); if (row == 0) cell.FontWeight = Microsoft.UI.Text.FontWeights.SemiBold; Grid.SetRow(cell, row); Grid.SetColumn(cell, col); grid.Children.Add(cell); }
        }
        return new ScrollViewer { Content = grid, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollBarVisibility = ScrollBarVisibility.Disabled };
    }
}
