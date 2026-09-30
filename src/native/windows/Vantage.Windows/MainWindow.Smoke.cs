using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Xaml.Automation.Provider;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Documents;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Vantage.Core;
using Vantage.Windows.Views;
namespace Vantage.Windows;

public sealed partial class MainWindow
{
    readonly Dictionary<Button, TaskCompletionSource<bool>> smokeButtonActions = [];
    ContentDialog? activeDialog;

    async Task RunSmokeAsync(string output)
    {
        var failures = new List<string>(); var evidence = new List<object>(); var actions = new List<string>();
        var directory = Path.GetDirectoryName(Path.GetFullPath(output))!; Directory.CreateDirectory(directory);
        async Task Capture(string name)
        {
            Root.UpdateLayout(); await Task.Delay(250);
            var path = await ScreenshotAsync(Path.Combine(directory, name + ".png"));
            if (new FileInfo(path).Length == 0) throw new InvalidDataException("Native screenshot is empty: " + name);
            evidence.Add(new { id = name, screenshot = path, render_error = (string?)null });
        }
        async Task Reveal(FrameworkElement target, string imageName)
        { target.StartBringIntoView(new BringIntoViewOptions { AnimationDesired = false, VerticalAlignmentRatio = 0 }); await Task.Delay(250); await Capture(imageName); }
        try
        {
            if (!ready) throw new InvalidOperationException("Backend initialization failed.");
            if (!onboarded)
            {
                await NavigateAsync("chat");
                if (selectedPage != "onboarding") throw new InvalidOperationException("Unfinished onboarding allowed navigation.");
                var before = CountVisuals(PageContent);
                if (onboardingFinish is null) throw new InvalidOperationException("Onboarding completion button is absent.");
                await Reveal(onboardingFinish, "onboarding-before-finish");
                await InvokeSmokeButtonAsync(onboardingFinish);
                if (!onboarded) throw new InvalidOperationException("The native onboarding button did not complete setup.");
                actions.Add("UIA onboarding Finish with explicit skip; unfinished navigation guarded");
                smokePages.Add(new { id = "onboarding", loaded = before > 5, explicit_skip = true, navigation_guard = true, screenshot = Path.Combine(directory, "onboarding-before-finish.png"), render_error = (string?)null });
            }
            foreach (var page in new[] { "dashboard", "plan", "chat", "projects", "finance", "plots", "face", "usage", "logs", "settings" })
            {
                await NavigateAsync(page); Root.UpdateLayout(); await Task.Delay(250);
                var count = CountVisuals(PageContent); var loaded = count >= 5 && StatusBar.Severity != InfoBarSeverity.Error;
                if (!loaded) failures.Add($"{page}: failed or empty native view");
                string? screenshot = null; string? renderError = null;
                try { screenshot = await ScreenshotAsync(Path.Combine(directory, page + ".png")); if (new FileInfo(screenshot).Length == 0) throw new InvalidDataException("Empty screenshot"); }
                catch (Exception e) { renderError = e.GetType().Name; failures.Add($"{page}: screenshot failed: {renderError}"); }
                smokePages.Add(new { id = page == "plan" ? "action-plan" : page, loaded, visual_count = count, native = true, screenshot, render_error = renderError });
                if (page == "plots")
                {
                    var charts = Visuals<NativeChart>(PageContent).ToArray();
                    if (charts.Length < 3) throw new InvalidDataException("Synthetic multi-axis/stack/radar charts are missing.");
                    for (var i = 0; i < charts.Length; i++) await Reveal(charts[i], $"plots-full-chart-{i + 1}");
                }
                if (page == "usage")
                { var speed = Visuals<NativeChart>(PageContent).LastOrDefault() ?? throw new InvalidDataException("Native speed chart is missing."); await Reveal(speed, "usage-speed"); }
                if (page == "settings")
                { var provider = Visuals<PasswordBox>(PageContent).FirstOrDefault() ?? throw new InvalidDataException("Native provider editor is missing."); await Reveal(provider, "settings-provider"); }
                if (page == "finance")
                {
                    await InvokeSmokeButtonAsync(Named<Button>("RecommendationsLoad"));
                    await Reveal(Named<StackPanel>("PurchaseRecommendations"), "finance-recommendations"); actions.Add("UIA load purchase recommendations");
                }
                if (page == "dashboard")
                {
                    var media = Named<ToggleSwitch>("LatestMediaToggle");
                    if (media.IsOn || Named<ToggleSwitch>("CameraToggle").IsOn) throw new InvalidDataException("Media was not hidden by default.");
                    await Reveal(Named<ToggleSwitch>("CameraToggle"), "dashboard-camera-hidden");
                    await Reveal(media, "dashboard-media-hidden");
                    ToggleSmokeControl(media);
                    await WaitSmokeAsync(() => Task.FromResult(Visuals<Image>(Named<StackPanel>("LatestMedia")).Count(Decoded) == 2), "Native media decode");
                    await Reveal(Named<StackPanel>("LatestMedia"), "dashboard-media-visible");
                    ToggleSmokeControl(media);
                    await WaitSmokeAsync(() => Task.FromResult(!Visuals<Image>(Named<StackPanel>("LatestMedia")).Any()), "Native media hide");
                    await InvokeSmokeButtonAsync(Named<Button>("PhotoFolder")); actions.Add("UIA media reveal/hide with decoded bitmaps; UIA open photo folder with backend intent");
                }
                if (page == "face")
                {
                    var toggle = Named<ToggleSwitch>("FacePhotoTogglelightest"); var image = Named<Image>("FacePhotolightest");
                    if (toggle.IsOn || image.Source is not null) throw new InvalidDataException("Face photo was not hidden by default.");
                    ToggleSmokeControl(toggle); await WaitSmokeAsync(() => Task.FromResult(Decoded(image)), "Native face photo decode");
                    await Reveal(toggle, "face-photo-visible"); ToggleSmokeControl(toggle);
                    await WaitSmokeAsync(() => Task.FromResult(image.Source is null), "Native face photo hide");
                    await Reveal(toggle, "face-photo-hidden"); actions.Add("UIA face photo reveal/decode/hide");
                }
            }
            await NavigateAsync("plan");
            await InvokeSmokeButtonAsync(Named<Button>("PlanGenerate"));
            var completed = (await api.JobsAsync()).Jobs.FirstOrDefault() ?? throw new InvalidDataException("No job was created by the native Generate button.");
            if (StatusBar.Severity != InfoBarSeverity.Success || completed.Status != "succeeded" || !JobObserver.MatchesSavedResult(completed.Result, await api.PlanAsync())) throw new InvalidDataException("The native plan workflow did not verify its saved result.");
            await Capture("plan-generated"); await Reveal(Named<StackPanel>("PlanSavedResult"), "plan-saved-content"); actions.Add("UIA Generate button; production observer and saved-result identity verification");

            // This route configures the already-verified isolated fixture, never a production backend.
            await api.PostAsync("/__test__/reset", new { onboarded = true, job_mode = "hold" });
            await NavigateAsync("plan"); var generateButton = Named<Button>("PlanGenerate");
            var pendingGeneration = InvokeSmokeButtonAsync(generateButton);
            string? heldJob = null;
            await WaitSmokeAsync(async () => { heldJob = (await api.JobsAsync()).Active?.Id; return heldJob is not null; }, "UI-generated cancellable job");
            if (generateButton.IsEnabled) throw new InvalidDataException("Repeated Generate was not disabled during an active request.");
            await InvokeSmokeButtonAsync(Named<Button>("PlanCancel")); await pendingGeneration;
            if ((await api.JobAsync(heldJob!)).Status != "cancelled") throw new InvalidDataException("The native Cancel button did not cancel the shared job.");
            actions.Add("UIA Generate/Cancel; repeated Generate disabled; canonical cancelled snapshot verified");

            await NavigateAsync("chat"); var input = Named<TextBox>("ChatInput");
            ((IValueProvider)new TextBoxAutomationPeer(input).GetPattern(PatternInterface.Value)).SetValue("Native smoke fixture");
            await InvokeSmokeButtonAsync(Named<Button>("ChatSend"));
            var context = await api.ChatContextAsync();
            if (!context.Messages.Any(m => m.Role == "user" && m.Content == "Native smoke fixture") || !VisibleText(PageContent).Contains("Native smoke fixture", StringComparison.Ordinal)) throw new InvalidDataException("The sent message is not both persisted and displayed by the native chat view.");
            await Capture("chat-sent"); await Reveal(Named<StackPanel>("ChatHistory"), "chat-messages"); await Reveal(input, "chat-input"); actions.Add("UIA text Value and Send; production stream/context display and persistence verified");
            var clearing = InvokeSmokeButtonAsync(Named<Button>("ChatClear"));
            await WaitSmokeAsync(() => Task.FromResult(activeDialog is not null && Visuals<Button>(activeDialog).Any(b => b.Content?.ToString() == activeDialog.PrimaryButtonText)), "Native clear confirmation dialog");
            var primary = Visuals<Button>(activeDialog!).First(b => b.Content?.ToString() == activeDialog!.PrimaryButtonText);
            ((IInvokeProvider)new ButtonAutomationPeer(primary).GetPattern(PatternInterface.Invoke)).Invoke(); await clearing;
            var cleared = await api.ChatContextAsync();
            if (cleared.Messages.Any(m => m.Role == "user" && m.Content == "Native smoke fixture") || VisibleText(PageContent).Contains("Native smoke fixture", StringComparison.Ordinal)) throw new InvalidDataException("Native clear did not adopt the authoritative base context.");
            await Capture("chat-cleared"); actions.Add("UIA Clear and native ContentDialog primary button; production reset and visible state verified");
        }
        catch (Exception e) { failures.Add(e.Message); }
        await File.WriteAllTextAsync(output, JsonSerializer.Serialize(new { success = failures.Count == 0, pages = smokePages, errors = failures, screenshots = evidence, actions, action_driver = "WinUI UI Automation Invoke/Value/Toggle and production event handlers; read-only API snapshots verify results" }, new JsonSerializerOptions { WriteIndented = true }));
        quitting = true; Environment.ExitCode = failures.Count == 0 ? 0 : 1; await ShutdownAsync(); Application.Current.Exit();
    }
    static bool Decoded(Image image) => image.Source is BitmapSource bitmap && bitmap.PixelWidth > 0 && bitmap.PixelHeight > 0;
    T Named<T>(string name) where T : FrameworkElement => Visuals<T>(PageContent).FirstOrDefault(x => x.Name == name) ?? throw new InvalidDataException("Missing native control: " + name);
    static IEnumerable<T> Visuals<T>(DependencyObject item) where T : DependencyObject
    {
        if (item is T result) yield return result;
        for (var i = 0; i < VisualTreeHelper.GetChildrenCount(item); i++) foreach (var child in Visuals<T>(VisualTreeHelper.GetChild(item, i))) yield return child;
    }
    static string VisibleText(DependencyObject item) => string.Join("\n", Visuals<TextBlock>(item).Select(x => x.Text + string.Concat(x.Inlines.OfType<Run>().Select(run => run.Text))));
    async Task InvokeSmokeButtonAsync(Button button)
    {
        button.StartBringIntoView(new BringIntoViewOptions { AnimationDesired = false }); await Task.Delay(100);
        var completion = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously); smokeButtonActions.Add(button, completion);
        try { ((IInvokeProvider)new ButtonAutomationPeer(button).GetPattern(PatternInterface.Invoke)).Invoke(); await completion.Task.WaitAsync(TimeSpan.FromSeconds(60)); }
        finally { smokeButtonActions.Remove(button); }
    }
    static void ToggleSmokeControl(ToggleSwitch toggle) => ((IToggleProvider)new ToggleSwitchAutomationPeer(toggle).GetPattern(PatternInterface.Toggle)).Toggle();
    async Task WaitSmokeAsync(Func<Task<bool>> condition, string phase)
    {
        var until = DateTimeOffset.UtcNow.AddSeconds(30);
        while (DateTimeOffset.UtcNow < until) { if (await condition()) return; await Task.Delay(100); }
        throw new TimeoutException(phase + ": " + StatusBar.Message);
    }
}
