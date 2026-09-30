using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Vantage.Core;
using Vantage.Windows.Platform;
namespace Vantage.Windows;
public sealed partial class MainWindow
{
    async Task SettingsAsync(CancellationToken ct)
    {
        settings = await api.SettingsAsync(ct); var state = settings;
        PageContent.Children.Add(Heading(T("设置", "Settings")));
        var language = Choice(T("显示语言", "Display language"), new[] { "system", "zh-CN", "en-US" }, state.Settings.String("display_language", "system"));
        var theme = Choice(T("主题", "Theme"), new[] { "auto", "light", "dark" }, state.Settings.String("theme_mode", "auto"));
        var startup = Check(T("登录时启动", "Launch at login"), state.Settings.Bool("launch_at_login"));
        var auto = Check(T("自动生成缺失的今日计划", "Generate a missing daily plan automatically"), state.Settings.Bool("action_plan_auto_generate"));
        var interval = new NumberBox { Header = T("数据变化检查间隔（分钟，0 关闭）", "Source check interval (minutes; 0 disables)"), Minimum = 0, Maximum = 35791, Value = state.Settings["action_plan_check_interval_minutes"]?.GetValue<int>() ?? 0, SpinButtonPlacementMode = NumberBoxSpinButtonPlacementMode.Inline };
        PageContent.Children.Add(Card(Stack(Text(T("通用", "General"), 20), Row(language, theme), startup,
            Text($"{T("系统区域", "System locale")}: {NativeDesktop.Locale}"), Text($"{T("原生启动项当前状态", "Current native login item")}: {NativeDesktop.StartupEnabled()}"), auto, interval)));
        var providersPanel = Stack(); var edits = new List<Func<(string route, JsonObject value, bool remove)>>();
        var routes = (state.Provider["providers"] as JsonObject)?.Select(p => p.Key).ToList() ?? [];
        var selected = Choice(T("默认 Provider", "Default provider"), routes, state.Provider.String("selected_provider"));
        selected.IsEditable = true;
        PageContent.Children.Add(Heading(T("AI 服务", "AI providers"))); PageContent.Children.Add(selected); PageContent.Children.Add(providersPanel);
        void AddProvider(string route, JsonObject provider, bool isNew)
        {
            var routeInput = Input(T("稳定标识", "Stable route"), route); routeInput.IsReadOnly = !isNew;
            var name = Input(T("名称", "Name"), provider.String("name", route));
            var enabled = Check(T("启用", "Enabled"), provider.Bool("enabled"));
            var url = Input("Base URL", provider.String("base_url"));
            var model = Input(T("默认模型", "Default model"), provider.String("model"));
            var key = new PasswordBox { Header = T("API 密钥（留空保留原值）", "API key (leave blank to preserve)"), PlaceholderText = provider.String("api_key") == "********" ? T("已有密钥", "Key saved") : T("未保存密钥", "No key saved"), PasswordRevealMode = PasswordRevealMode.Hidden };
            var clearKey = Check(T("明确清除已保存密钥", "Clear saved key"), false);
            var models = Input(T("模型列表（每行一个）", "Models (one per line)"), string.Join("\n", (provider["models"] as JsonArray ?? []).Select(x => x?.GetValue<string>())), true);
            var context = new NumberBox { Header = T("上下文容量（0 使用默认）", "Context tokens (0 = default)"), Minimum = 0, Maximum = 100000000, Value = provider["context_window_tokens"]?.GetValue<int>() ?? 0 };
            var output = new NumberBox { Header = T("最大输出（0 使用默认）", "Output tokens (0 = default)"), Minimum = 0, Maximum = 100000000, Value = provider["max_output_tokens"]?.GetValue<int>() ?? 0 };
            var removed = false;
            var panel = Stack(Row(routeInput, name), enabled, url, key, clearKey, model, models, Row(context, output));
            var card = Card(panel);
            panel.Children.Add(Row(ActionButton(T("发现模型", "Discover models"), async () =>
            {
                var request = new JsonObject { ["route"] = routeInput.Text, ["base_url"] = url.Text, ["type"] = "openai-compatible" };
                if (!string.IsNullOrEmpty(key.Password)) request["api_key"] = key.Password;
                var discovered = await api.PostAsync("/api/v1/models/discover", request, ct);
                models.Text = string.Join("\n", discovered.Field("models").Items().Select(x => x.Text()));
                if (model.Text.Length == 0) model.Text = discovered.Field("models").Items().FirstOrDefault().Text();
            }), ActionButton(T("移除 Provider", "Remove provider"), async () =>
            {
                if (await ConfirmAsync(T("移除服务", "Remove provider"), T("保存设置时将删除此 Provider 及其密钥，继续吗？", "Saving will remove this provider and its saved key. Continue?"))) { removed = true; card.Visibility = Visibility.Collapsed; key.Password = ""; }
            })));
            providersPanel.Children.Add(card);
            edits.Add(() =>
            {
                if (string.IsNullOrWhiteSpace(routeInput.Text)) throw new InvalidDataException(T("Provider 标识不能为空", "A provider route is required"));
                var result = new JsonObject { ["route"] = routeInput.Text.Trim(), ["name"] = name.Text, ["type"] = "openai-compatible", ["enabled"] = enabled.IsChecked == true, ["base_url"] = url.Text.Trim(), ["model"] = model.Text.Trim(), ["models"] = new JsonArray(models.Text.Split(['\n', '\r'], StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries).Distinct().Select(x => (JsonNode?)JsonValue.Create(x)).ToArray()) };
                if (context.Value > 0 && double.IsFinite(context.Value)) result["context_window_tokens"] = (int)context.Value;
                if (output.Value > 0 && double.IsFinite(output.Value)) result["max_output_tokens"] = (int)output.Value;
                if (clearKey.IsChecked == true) result["api_key"] = ""; else if (key.Password.Length > 0) result["api_key"] = key.Password;
                return (routeInput.Text.Trim(), result, removed);
            });
        }
        foreach (var p in state.Provider["providers"] as JsonObject ?? []) if (p.Value is JsonObject provider) AddProvider(p.Key, provider, false);
        PageContent.Children.Add(ActionButton(T("添加 Provider", "Add provider"), () => { AddProvider("", new JsonObject { ["enabled"] = true }, true); return Task.CompletedTask; }));
        var sampling = Input(T("采样默认值（JSON）", "Sampling defaults (JSON)"), state.Provider["sampling_defaults"]?.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) ?? "{}", true);
        var profiles = Input(T("模型参数配置（JSON）", "Model profiles (JSON)"), state.Provider["model_profiles"]?.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) ?? "{}", true);
        PageContent.Children.Add(new Expander { Header = T("高级模型参数", "Advanced model parameters"), Content = Stack(Text(T("支持 parameters、omit_parameters、extra、max_tokens、reasoning_tiers、reasoning_aliases；后端校验这些设置。", "Profiles support parameters, omit_parameters, extra, max_tokens, reasoning_tiers and reasoning_aliases; the backend validates them.")), sampling, profiles), HorizontalAlignment = HorizontalAlignment.Stretch });
        var special = new List<Func<JsonObject>>();
        foreach (var kind in new[] { "voice", "image" })
        {
            var mode = Choice(T("服务模式", "Provider mode"), new[] { "inherit_ai", "custom" }, state.Settings.String(kind + "_provider_mode", "inherit_ai"));
            var url = Input("Base URL", state.Settings.String(kind + "_base_url"));
            var key = new PasswordBox { Header = T("API 密钥（留空保留）", "API key (blank preserves)"), PlaceholderText = state.Settings.Bool(kind + "_has_api_key") ? T("已有密钥", "Key saved") : "", PasswordRevealMode = PasswordRevealMode.Hidden };
            var clear = Check(T("清除已保存密钥", "Clear saved key"), false);
            var model = Choice(T("模型", "Model"), (state.Settings[kind + "_models"] as JsonArray ?? []).Select(x => x?.GetValue<string>() ?? ""), state.Settings.String(kind + "_model")); model.IsEditable = true; model.Text = state.Settings.String(kind + "_model");
            var savedModels = (state.Settings[kind + "_models"] as JsonArray)?.DeepClone() as JsonArray ?? [];
            var discovery = ActionButton(T("发现模型", "Discover models"), async () =>
            {
                var request = new JsonObject { ["kind"] = kind, ["mode"] = Value(mode), ["base_url"] = url.Text, ["type"] = "openai-compatible" };
                if (key.Password.Length > 0) request["api_key"] = key.Password;
                var data = await api.PostAsync("/api/v1/providers/models/discover", request, ct);
                model.Items.Clear(); savedModels.Clear(); foreach (var m in data.Field("models").Items()) { model.Items.Add(m.Text()); savedModels.Add(m.Text()); } if (model.Items.Count > 0) model.SelectedIndex = 0;
            });
            PageContent.Children.Add(Card(Stack(Text(kind == "voice" ? T("语音转录", "Voice transcription") : T("图像服务", "Image provider"), 20), mode, url, key, clear, model, discovery)));
            special.Add(() =>
            {
                var value = new JsonObject { [kind + "_provider_mode"] = Value(mode), [kind + "_base_url"] = url.Text.Trim(), [kind + "_model"] = Value(model), [kind + "_models"] = savedModels.DeepClone() };
                if (clear.IsChecked == true) value[kind + "_api_key"] = ""; else if (key.Password.Length > 0) value[kind + "_api_key"] = key.Password;
                return value;
            });
        }
        PageContent.Children.Add(ActionButton(T("保存全部设置", "Save settings"), async () =>
        {
            if (!double.IsFinite(interval.Value) || interval.Value != Math.Truncate(interval.Value)) throw new InvalidDataException(T("检查间隔必须为整数", "Check interval must be a whole number"));
            // Re-read immediately before replacing the providers map so other providers are preserved.
            var latest = await api.SettingsAsync(ct); var providers = (JsonObject?)(latest.Provider["providers"]?.DeepClone()) ?? [];
            var seen = new HashSet<string>();
            foreach (var edit in edits)
            {
                var (route, value, remove) = edit(); if (!seen.Add(route)) throw new InvalidDataException(T("Provider 标识重复", "Duplicate provider route"));
                if (remove) { providers.Remove(route); continue; }
                var merged = (JsonObject?)(providers[route]?.DeepClone()) ?? [];
                // Never replay a masked credential; omission is the write-only preserve operation.
                merged.Remove("api_key"); foreach (var property in value) merged[property.Key] = property.Value?.DeepClone(); providers[route] = merged;
            }
            var defaultRoute = Value(selected); if (providers.Count > 0 && !providers.ContainsKey(defaultRoute)) throw new InvalidDataException(T("请选择存在的默认 Provider", "Choose an existing default provider"));
            var patch = new JsonObject {
                ["display_language"] = Value(language), ["theme_mode"] = Value(theme), ["theme"] = Value(theme) == "auto" ? (Root.ActualTheme == ElementTheme.Dark ? "dark" : "light") : Value(theme),
                ["launch_at_login"] = startup.IsChecked == true, ["action_plan_auto_generate"] = auto.IsChecked == true, ["action_plan_check_interval_minutes"] = (int)interval.Value,
                ["provider_config"] = new JsonObject { ["selected_provider"] = providers.Count > 0 ? defaultRoute : null, ["providers"] = providers,
                    ["sampling_defaults"] = JsonNode.Parse(sampling.Text) as JsonObject ?? throw new InvalidDataException("Sampling defaults must be an object."),
                    ["model_profiles"] = JsonNode.Parse(profiles.Text) as JsonObject ?? throw new InvalidDataException("Model profiles must be an object.") }
            };
            foreach (var collect in special) foreach (var property in collect()) patch[property.Key] = property.Value?.DeepClone();
            await api.UpdateSettingsAsync(patch, ct); settings = await api.SettingsAsync(ct);
            NativeDesktop.SetStartup(settings.Settings.Bool("launch_at_login")); ApplyAppearance(); BuildNavigation(); UpdateTray();
            await NavigateAsync("settings"); Status(T("设置与原生选项已保存", "Settings and native preferences saved"), InfoBarSeverity.Success);
        }));
        var paths = Stack(Text(T("数据与日志", "Data and logs"), 20));
        foreach (var entry in state.RuntimePaths)
        {
            var key = entry.Key.Replace("_dir", ""); if (key is not ("config" or "history" or "logs" or "log" or "plots" or "plot" or "cache" or "runtime" or "data")) continue;
            paths.Children.Add(Row(Text(entry.Key + ": " + entry.Value), ActionButton(T("打开", "Open"), () => { NativeDesktop.OpenPath(entry.Value); return Task.CompletedTask; })));
        }
        PageContent.Children.Add(Card(paths));
        PageContent.Children.Add(Card(Stack(Text(T("系统权限", "OS permissions"), 20), Row(
            ActionButton(T("相机", "Camera"), () => { NativeDesktop.PermissionSettings("webcam"); return Task.CompletedTask; }),
            ActionButton(T("麦克风", "Microphone"), () => { NativeDesktop.PermissionSettings("microphone"); return Task.CompletedTask; }),
            ActionButton(T("位置", "Location"), () => { NativeDesktop.PermissionSettings("location"); return Task.CompletedTask; })),
            Text(T("窗口关闭后驻留托盘；托盘菜单可退出。只有本应用启动的后端会随退出停止。", "Closing the window keeps Vantage in the tray. Quit from its menu; only a backend started by this app is stopped.")))));
    }
    async Task OnboardingAsync(CancellationToken ct)
    {
        var onboarding = await api.OnboardingAsync(ct);
        PageContent.Children.Add(Heading(T("欢迎使用 Vantage", "Welcome to Vantage")));
        PageContent.Children.Add(Text(T("数据保留在本机。配置的模型与语音服务会接收你主动请求分析的内容。", "Your data stays on this computer. Configured model and voice services receive content you request them to process.")));
        var language = Choice(T("显示语言", "Display language"), new[] { "system", "zh-CN", "en-US" }, onboarding.DisplayLanguage);
        var startup = Check(T("登录时启动", "Launch at login"), onboarding.LaunchAtLogin);
        var skip = Check(T("暂不配置对话服务（保留已有设置）", "Skip chat setup (preserve existing configuration)"), true);
        var route = Input(T("Provider 标识", "Provider route"), "custom"); var url = Input("Base URL"); var model = Input(T("模型", "Model"));
        var key = new PasswordBox { Header = "API key", PasswordRevealMode = PasswordRevealMode.Hidden };
        var provider = Stack(route, url, key, model); provider.IsEnabled = false; skip.Checked += (_, _) => provider.IsEnabled = false; skip.Unchecked += (_, _) => provider.IsEnabled = true;
        var import = Check(T("从选定目录导入已有数据", "Import existing data from a chosen folder"), false); var directory = Input(T("导入源目录", "Source folder")); directory.IsReadOnly = true;
        PageContent.Children.Add(Card(Stack(language, startup, skip, provider)));
        PageContent.Children.Add(new Expander { Header = T("导入已有数据（可选）", "Import existing data (optional)"), Content = Stack(import, directory, ActionButton(T("选择目录", "Choose folder"), async () => { var path = await NativeDesktop.PickFolderAsync(this); if (path is not null) directory.Text = path; })), HorizontalAlignment = HorizontalAlignment.Stretch });
        PageContent.Children.Add(ActionButton(T("完成设置", "Finish setup"), async () =>
        {
            if (import.IsChecked == true && (directory.Text.Length == 0 || !await ConfirmAsync(T("导入数据", "Import data"), directory.Text + "\n" + T("从此目录复制缺少的历史和状态文件？", "Copy missing history and state files from this folder?")))) return;
            var value = new JsonObject { ["skip_chat_setup"] = skip.IsChecked == true, ["display_language"] = Value(language), ["launch_at_login"] = startup.IsChecked == true, ["import_legacy_data"] = import.IsChecked == true };
            if (skip.IsChecked != true) { value["selected_provider"] = route.Text.Trim(); value["base_url"] = url.Text.Trim(); value["model"] = model.Text.Trim(); if (key.Password.Length > 0) value["api_key"] = key.Password; }
            if (import.IsChecked == true) value["legacy_root"] = directory.Text;
            await api.CompleteOnboardingAsync(value, ct);
            if (!(await api.OnboardingAsync(ct)).Completed) throw new InvalidDataException(T("引导尚未完成", "Setup has not completed"));
            key.Password = ""; settings = await api.SettingsAsync(ct); NativeDesktop.SetStartup(settings.Settings.Bool("launch_at_login")); ApplyAppearance(); BuildNavigation(); UpdateTray(); await NavigateAsync("dashboard");
        }));
    }
}
