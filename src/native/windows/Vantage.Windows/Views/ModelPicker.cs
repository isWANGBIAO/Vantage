using System.Text.Json;
using Microsoft.UI.Xaml.Controls;
using Vantage.Core;
namespace Vantage.Windows.Views;
public sealed class ModelPicker : StackPanel
{
    readonly ComboBox models = new() { Header = "模型 / Model", MinWidth = 260 };
    readonly ComboBox reasoning = new() { Header = "推理 / Reasoning", MinWidth = 160 };
    readonly ComboBox tier = new() { Header = "服务层级 / Service tier", MinWidth = 160 };
    readonly JsonElement[] options;
    public ModelPicker(JsonElement catalog)
    {
        Orientation = Orientation.Horizontal; Spacing = 14; options = catalog.Field("model_options").Items().ToArray();
        foreach (var option in options) models.Items.Add(option.Field("label").Text(option.Field("model").Text()));
        foreach (var value in new[] { "default", "priority", "fast" }) tier.Items.Add(value); tier.SelectedIndex = 0;
        models.SelectionChanged += (_, _) => RefreshReasoning();
        models.SelectedIndex = Array.FindIndex(options, x => x.Field("is_default").ValueKind == JsonValueKind.True);
        if (models.SelectedIndex < 0 && options.Length > 0) models.SelectedIndex = 0;
        RefreshReasoning(); Children.Add(models); Children.Add(reasoning); Children.Add(tier);
    }
    JsonElement Selected => models.SelectedIndex >= 0 && models.SelectedIndex < options.Length ? options[models.SelectedIndex] : default;
    void RefreshReasoning()
    {
        reasoning.Items.Clear(); reasoning.Items.Add("default");
        foreach (var item in Selected.Field("reasoning_tiers").Items()) reasoning.Items.Add(item.Text());
        reasoning.SelectedIndex = 0; reasoning.IsEnabled = reasoning.Items.Count > 1;
    }
    public string? Model => Selected.Field("model").Text() is { Length: > 0 } value ? value : null;
    public string? Route => Selected.Field("provider_route").Text() is { Length: > 0 } value ? value : null;
    public string? Reasoning => reasoning.SelectedItem?.ToString() is { } value && value != "default" ? value : null;
    public string? Tier => tier.SelectedItem?.ToString() is { } value && value != "default" ? value : null;
}
