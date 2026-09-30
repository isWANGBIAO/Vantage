using Microsoft.UI.Xaml;
using Vantage.Windows.Platform;
namespace Vantage.Windows;
public partial class App : Application
{
    Mutex? singleton;
    MainWindow? window;
    public App() { InitializeComponent(); }
    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        singleton = new Mutex(true, "Local\\Vantage.Native.WinUI", out var first);
        if (!first) { NativeDesktop.ActivateExisting(); Exit(); return; }
        window = new MainWindow(); window.Activate();
    }
}
