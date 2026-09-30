using Microsoft.UI.Xaml;
using Vantage.Windows.Platform;
namespace Vantage.Windows;
public partial class App : Application
{
    Mutex? singleton;
    MainWindow? window;
    public App()
    {
        SmokeDiagnostics.Record("App.ctor");
        UnhandledException += (sender, e) => { SmokeDiagnostics.Fail("WinUI.UnhandledException", e.Exception); /* Do not mark handled or report a false pass. */ };
        try { SmokeDiagnostics.Record("App.InitializeComponent.before"); InitializeComponent(); SmokeDiagnostics.Record("App.InitializeComponent.after"); }
        catch (Exception e) { SmokeDiagnostics.Fail("App.InitializeComponent.failed", e); throw; }
    }
    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        SmokeDiagnostics.Record("App.OnLaunched");
        singleton = new Mutex(true, "Local\\Vantage.Native.WinUI", out var first);
        if (!first) { SmokeDiagnostics.Record("Existing native instance"); NativeDesktop.ActivateExisting(); Exit(); return; }
        try
        {
            SmokeDiagnostics.Record("MainWindow.ctor.before"); window = new MainWindow(); SmokeDiagnostics.Record("MainWindow.ctor.after");
            SmokeDiagnostics.Record("MainWindow.Activate.before"); window.Activate(); SmokeDiagnostics.Record("MainWindow.Activate.after");
        }
        catch (Exception e) { SmokeDiagnostics.Fail("App.OnLaunched.failed", e); throw; }
    }
}
