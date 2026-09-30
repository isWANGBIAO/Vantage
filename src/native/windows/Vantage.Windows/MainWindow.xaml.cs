using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Xaml.Automation.Provider;
using Vantage.Core;
using Vantage.Windows.Platform;
using Vantage.Windows.Views;
using Windows.Storage.Streams;
using Windows.Storage;
using Windows.Graphics.Imaging;
namespace Vantage.Windows;

public sealed partial class MainWindow : Window
{
    Grid Root = null!;
    NavigationView Navigation = null!;
    ScrollViewer PageScroll = null!;
    StackPanel PageContent = null!;
    InfoBar StatusBar = null!;
    readonly ApiClient api;
    readonly BackendHost host;
    readonly CancellationTokenSource lifetime = new();
    CancellationTokenSource pageLifetime = new();
    CancellationTokenSource? chatLifetime;
    CancellationTokenSource? transcriptionLifetime;
    Task? transcriptionTask;
    bool shutdownStarted, shutdownComplete;
    SettingsState? settings;
    TrayIcon? tray;
    readonly VoiceRecorder recorder = new();
    bool ready, quitting, onboarded, isWindowVisible = true;
    Button? onboardingFinish;
    readonly List<ToggleSwitch> privacyToggles = [];
    int navigationEpoch;
    string selectedPage = "dashboard";
    bool English => settings?.Settings.String("display_language", "system") is "en-US" || (settings?.Settings.String("display_language", "system") is not "zh-CN" && !NativeDesktop.Locale.StartsWith("zh"));
    string T(string zh, string en) => English ? en : zh;
    readonly string? smokeOutput;
    readonly List<object> smokePages = [];
    public MainWindow()
    {
        SmokeDiagnostics.Record("MainWindow.InitializeShell.before");
        InitializeShell();
        SmokeDiagnostics.Record("MainWindow.InitializeShell.after");
        api = new ApiClient(BackendAddress.Resolve()); host = new BackendHost(api);
        var args = Environment.GetCommandLineArgs();
        var i = Array.IndexOf(args, "--smoke-test"); smokeOutput = i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
        SmokeDiagnostics.Record("MainWindow.Resize.before");
        AppWindow.Resize(new global::Windows.Graphics.SizeInt32(1240, 900));
        SmokeDiagnostics.Record("MainWindow.Resize.after");
        var iconPath = Path.Combine(AppContext.BaseDirectory, "Assets", "Vantage.ico");
        if (File.Exists(iconPath)) AppWindow.SetIcon(iconPath);
        AppWindow.Closing += (sender, e) =>
        {
            if (!quitting && smokeOutput is null && tray is not null) { e.Cancel = true; AppWindow.Hide(); }
            else if (!shutdownComplete) { e.Cancel = true; _ = ShutdownAsync(); }
        };
        VisibilityChanged += async (_, visibility) =>
        {
            isWindowVisible = visibility.Visible;
            if (!visibility.Visible) { foreach (var toggle in privacyToggles.ToArray()) toggle.IsOn = false; await StopAudioAsync(); }
        };
        Closed += (_, _) => { if (!shutdownComplete) { lifetime.Cancel(); host.Dispose(); } };
        Root.ActualThemeChanged += (_, _) => ApplyAppearance();
        Root.Loaded += async (_, _) => { SmokeDiagnostics.Record("Root.Loaded"); await InitializeAsync(); if (smokeOutput is not null) await RunSmokeAsync(smokeOutput); };
    }
    void InitializeShell()
    {
        Title = "Vantage";
        SmokeDiagnostics.Record("Shell.Grid.before");
        Root = new Grid { Style = (Style)Application.Current.Resources["VantageRootStyle"] };
        Root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        Root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        SmokeDiagnostics.Record("Shell.NavigationView.before");
        Navigation = new NavigationView { IsBackButtonVisible = NavigationViewBackButtonVisible.Collapsed,
            PaneDisplayMode = NavigationViewPaneDisplayMode.Auto, IsSettingsVisible = true, Header = "Vantage" };
        PageContent = new StackPanel { Padding = new Thickness(28), Spacing = 18, MaxWidth = 1500, HorizontalAlignment = HorizontalAlignment.Stretch };
        PageScroll = new ScrollViewer { HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled, Content = PageContent };
        Navigation.Content = PageScroll;
        Navigation.SelectionChanged += Navigation_SelectionChanged;
        SmokeDiagnostics.Record("Shell.InfoBar.before");
        StatusBar = new InfoBar { IsOpen = true, IsClosable = false, Severity = InfoBarSeverity.Informational,
            Title = "Vantage", Message = "Connecting to the local backend…" };
        Grid.SetRow(StatusBar, 1); Root.Children.Add(Navigation); Root.Children.Add(StatusBar);
        Content = Root;
        SmokeDiagnostics.Record("Shell.Content.assigned");
    }
    async Task InitializeAsync()
    {
        try
        {
            Status(T("正在连接本机后端…", "Connecting to the local backend…"));
            if (smokeOutput is not null)
            {
                using var fixtureCheck = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token); fixtureCheck.CancelAfter(TimeSpan.FromSeconds(10));
                await api.VerifySyntheticFixtureAsync(fixtureCheck.Token);
            }
            await host.StartOrConnectAsync(smokeOutput is not null, lifetime.Token);
            settings = await api.SettingsAsync(lifetime.Token); ApplyAppearance(); BuildNavigation();
            if (smokeOutput is null)
            {
                tray ??= new TrayIcon(this, () => { AppWindow.Show(); Activate(); }, Quit);
                UpdateTray();
                // On startup, shared settings are authoritative, including changes from CLI or another UI.
                NativeDesktop.SetStartup(settings.Settings.Bool("launch_at_login"));
            }
            var onboard = await api.OnboardingAsync(lifetime.Token); onboarded = onboard.Completed; BuildNavigation(); ready = true;
            await NavigateAsync(onboard.Completed ? "dashboard" : "onboarding");
            if (Environment.GetCommandLineArgs().Contains("--background")) AppWindow.Hide();
        }
        catch (Exception e)
        {
            ShowError(e); PageContent.Children.Clear(); PageContent.Children.Add(Heading(T("连接未就绪", "Backend unavailable")));
            PageContent.Children.Add(Text(T("确保本机 Vantage 后端已启动，或使用包含 backend-runtime 的完整安装包。", "Start the local Vantage backend or use the complete package containing backend-runtime.")));
            PageContent.Children.Add(ActionButton(T("重新连接", "Reconnect"), InitializeAsync));
        }
    }
    void BuildNavigation()
    {
        Navigation.MenuItems.Clear(); Navigation.IsSettingsVisible = onboarded; Navigation.IsPaneToggleButtonVisible = onboarded;
        if (Navigation.SettingsItem is NavigationViewItem settingsItem) settingsItem.Content = T("设置", "Settings");
        foreach (var (id, zh, en, icon) in new[] {
            ("dashboard", "概览", "Dashboard", Symbol.Home), ("plan", "行动计划", "Action plan", Symbol.Bullets),
            ("chat", "对话", "Chat", Symbol.Message), ("projects", "项目进度", "Projects", Symbol.Flag),
            ("finance", "资产与消费", "Expenses", Symbol.Shop), ("plots", "数据图表", "Plots", Symbol.ShowResults),
            ("face", "面部历史", "Face history", Symbol.Contact), ("usage", "模型用量", "Usage", Symbol.Calculator),
            ("logs", "系统日志", "System logs", Symbol.Document) })
            Navigation.MenuItems.Add(new NavigationViewItem { Content = T(zh, en), Tag = id, Icon = new SymbolIcon(icon), IsEnabled = onboarded });
    }
    async void Navigation_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (!ready) return;
        var id = args.IsSettingsSelected ? "settings" : (args.SelectedItem as NavigationViewItem)?.Tag as string;
        if (id is not null) await NavigateAsync(id);
    }
    async Task NavigateAsync(string id)
    {
        if (!ready) return;
        if (!onboarded && id != "onboarding") id = "onboarding";
        var epoch = ++navigationEpoch;
        pageLifetime.Cancel(); pageLifetime.Dispose(); pageLifetime = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token);
        chatLifetime?.Cancel(); await StopAudioAsync();
        if (epoch != navigationEpoch) return;
        if (selectedPage == "face" && id != "face") { try { await api.GetAsync<JsonElement>("/api/v1/face/live?active=false", lifetime.Token); } catch { } }
        if (epoch != navigationEpoch) return;
        selectedPage = id; privacyToggles.Clear(); PageContent.Children.Clear(); PageScroll.ChangeView(null, 0, null);
        var ct = pageLifetime.Token;
        try
        {
            switch (id)
            {
                case "dashboard": await DashboardAsync(ct); break;
                case "plan": await PlanAsync(ct); break;
                case "chat": await ChatAsync(ct); break;
                case "projects": await ProjectsAsync(ct); break;
                case "finance": await FinanceAsync(ct); break;
                case "plots": await PlotsAsync(ct); break;
                case "face": await FaceAsync(ct); break;
                case "usage": await UsageAsync(ct); break;
                case "logs": await LogsAsync(ct); break;
                case "settings": await SettingsAsync(ct); break;
                case "onboarding": await OnboardingAsync(ct); break;
            }
            if (!ct.IsCancellationRequested) Status(T("已连接 · 本机共享后端", "Connected · shared local backend"));
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested) { }
        catch (Exception e) { if (!ct.IsCancellationRequested) { ShowError(e); PageContent.Children.Add(ActionButton(T("重试", "Retry"), () => NavigateAsync(id))); } }
        finally { /* Navigation cancellation owns stale-page disposal. */ }
    }
    void Quit() { quitting = true; Close(); }
    async Task StopAudioAsync()
    {
        transcriptionLifetime?.Cancel();
        if (transcriptionTask is not null) { try { await transcriptionTask; } catch (Exception) { /* Caller displays upload errors; cleanup still runs. */ } }
        await recorder.DisposeAsync();
    }
    async Task ShutdownAsync()
    {
        if (shutdownStarted) return; shutdownStarted = true; quitting = true;
        // Closing can synchronously invoke this method; let its cancelled event unwind before Close().
        await Task.Yield();
        lifetime.Cancel(); pageLifetime.Cancel(); chatLifetime?.Cancel();
        try { await StopAudioAsync(); }
        finally { tray?.Dispose(); host.Dispose(); api.Dispose(); shutdownComplete = true; Close(); }
    }
    void Status(string message, InfoBarSeverity severity = InfoBarSeverity.Informational) { StatusBar.Message = message; StatusBar.Severity = severity; StatusBar.IsOpen = true; }
    void ShowError(Exception e) => Status(e is OperationCanceledException ? T("请求超时或已停止", "Request timed out or stopped") : e.Message, InfoBarSeverity.Error);
    Button ActionButton(string title, Func<Task> action)
    {
        var button = new Button { Content = title };
        button.Click += async (sender, args) =>
        {
            button.IsEnabled = false; Exception? failure = null;
            try { await action(); }
            catch (OperationCanceledException e) { failure = e; }
            catch (Exception e) { failure = e; ShowError(e); }
            finally
            {
                button.IsEnabled = true;
                if (smokeButtonActions.TryGetValue(button, out var completion))
                { if (failure is null) completion.TrySetResult(true); else completion.TrySetException(failure); }
            }
        };
        return button;
    }
    static TextBlock Text(string value, double size = 14) => new() { Text = value, FontSize = size, TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true };
    static TextBlock Heading(string value) => new() { Text = value, FontSize = 28, FontWeight = Microsoft.UI.Text.FontWeights.SemiBold, TextWrapping = TextWrapping.Wrap };
    static StackPanel Stack(params UIElement[] elements) { var s = new StackPanel { Spacing = 12 }; foreach (var e in elements) s.Children.Add(e); return s; }
    static StackPanel Row(params UIElement[] elements) { var s = Stack(elements); s.Orientation = Orientation.Horizontal; return s; }
    static Border Card(UIElement child) => new() { Child = child, Style = (Style)Application.Current.Resources["VantageCardStyle"] };
    static TextBox Input(string label, string value = "", bool multi = false) => new() { Header = label, Text = value, AcceptsReturn = multi, TextWrapping = multi ? TextWrapping.Wrap : TextWrapping.NoWrap, MinWidth = 240, MaxHeight = multi ? 240 : 100, HorizontalAlignment = HorizontalAlignment.Stretch };
    static ComboBox Choice(string label, IEnumerable<string> options, string? selected = null)
    { var box = new ComboBox { Header = label, MinWidth = 180 }; foreach (var item in options) box.Items.Add(item); box.SelectedItem = selected; if (box.SelectedIndex < 0 && box.Items.Count > 0) box.SelectedIndex = 0; return box; }
    static string Value(ComboBox box) => box.IsEditable ? box.Text : box.SelectedItem?.ToString() ?? "";
    static CheckBox Check(string title, bool value) => new() { Content = title, IsChecked = value };
    static void AppendBounded(TextBox output, string line) { output.Text += line + "\n"; if (output.Text.Length > 64000) output.Text = output.Text[^64000..]; }
    async Task<bool> ConfirmAsync(string title, string message)
    {
        var dialog = new ContentDialog { XamlRoot = Root.XamlRoot, Title = title, Content = Text(message), PrimaryButtonText = T("确认", "Confirm"), CloseButtonText = T("取消", "Cancel"), DefaultButton = ContentDialogButton.Close };
        activeDialog = dialog;
        try { return await dialog.ShowAsync() == ContentDialogResult.Primary; }
        finally { activeDialog = null; }
    }
    void ApplyAppearance()
    {
        NativeDataView.English = English;
        var theme = settings?.Settings.String("theme_mode", "auto");
        Root.RequestedTheme = theme switch { "dark" => ElementTheme.Dark, "light" => ElementTheme.Light, _ => ElementTheme.Default };
        var dark = Root.ActualTheme == ElementTheme.Dark;
        if (!Microsoft.UI.Windowing.AppWindowTitleBar.IsCustomizationSupported()) return;
        AppWindow.TitleBar.BackgroundColor = dark ? Colors.Black : Colors.White;
        AppWindow.TitleBar.ForegroundColor = dark ? Colors.White : Colors.Black;
        AppWindow.TitleBar.ButtonBackgroundColor = dark ? Colors.Black : Colors.White;
        AppWindow.TitleBar.ButtonForegroundColor = dark ? Colors.White : Colors.Black;
    }
    void UpdateTray() { if (tray is not null) { tray.ShowLabel = T("打开 Vantage", "Open Vantage"); tray.ExitLabel = T("退出", "Quit"); } }
    async Task ImageBytesAsync(Image image, byte[] bytes, CancellationToken ct = default)
    {
        using var random = new InMemoryRandomAccessStream(); using (var writer = new DataWriter(random.GetOutputStreamAt(0))) { writer.WriteBytes(bytes); await writer.StoreAsync(); }
        random.Seek(0); var bitmap = new BitmapImage(); await bitmap.SetSourceAsync(random); ct.ThrowIfCancellationRequested(); image.Source = bitmap;
    }
    async Task PollAsync(Func<Task> load, TimeSpan interval, CancellationToken ct)
    {
        try { while (!ct.IsCancellationRequested) { await Task.Delay(interval, ct); if (isWindowVisible) await load(); } }
        catch (OperationCanceledException) when (ct.IsCancellationRequested) { }
        catch (Exception e) { if (!ct.IsCancellationRequested) { ShowError(e); StatusBar.Message += T("；点击刷新重试", "; use Refresh to reconnect"); } }
    }
    UIElement DataView(JsonElement data, string? label = null) => NativeDataView.Create(data, label);
    async Task<string> ScreenshotAsync(string path)
    {
        var bitmap = new RenderTargetBitmap(); await bitmap.RenderAsync(Root);
        if (bitmap.PixelWidth == 0 || bitmap.PixelHeight == 0) throw new InvalidOperationException("Native render is empty.");
        var buffer = await bitmap.GetPixelsAsync(); var pixels = new byte[checked((int)buffer.Length)];
        using (var reader = DataReader.FromBuffer(buffer)) reader.ReadBytes(pixels);
        var folder = await StorageFolder.GetFolderFromPathAsync(Path.GetDirectoryName(path)!);
        var file = await folder.CreateFileAsync(Path.GetFileName(path), CreationCollisionOption.ReplaceExisting);
        using var stream = await file.OpenAsync(FileAccessMode.ReadWrite);
        var encoder = await BitmapEncoder.CreateAsync(BitmapEncoder.PngEncoderId, stream);
        encoder.SetPixelData(BitmapPixelFormat.Bgra8, BitmapAlphaMode.Premultiplied, (uint)bitmap.PixelWidth, (uint)bitmap.PixelHeight, 96, 96, pixels);
        await encoder.FlushAsync(); return path;
    }
    static int CountVisuals(DependencyObject item) { var count = 1; for (int i = 0; i < VisualTreeHelper.GetChildrenCount(item); i++) count += CountVisuals(VisualTreeHelper.GetChild(item, i)); return count; }
}
