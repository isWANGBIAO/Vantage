using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
namespace Vantage.Windows.Views;
public static class MarkdownView
{
    // Native selectable paragraphs. Never interprets embedded HTML or remote scripts/images.
    public static StackPanel Create(string markdown)
    {
        var panel = new StackPanel { Spacing = 8 }; var code = false;
        foreach (var line in markdown.Replace("\r", "").Split('\n'))
        {
            if (line.StartsWith("```")) { code = !code; continue; }
            var level = line.TakeWhile(x => x == '#').Count();
            var value = level > 0 && level < 7 ? line[level..].TrimStart() : line;
            var block = new TextBlock { Text = value, TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true,
                FontSize = level > 0 && level < 7 ? Math.Max(16, 27 - level * 2) : 14,
                FontWeight = level > 0 && level < 7 ? Microsoft.UI.Text.FontWeights.SemiBold : Microsoft.UI.Text.FontWeights.Normal };
            if (code) block.FontFamily = new FontFamily("Consolas"); panel.Children.Add(block);
        }
        return panel;
    }
}
