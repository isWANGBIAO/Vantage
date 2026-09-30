using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Vantage.Windows.Platform;
namespace Vantage.Windows;

internal static class Program
{
    [STAThread]
    public static void Main(string[] args)
    {
        SmokeDiagnostics.Record("Program.Main");
        AppDomain.CurrentDomain.UnhandledException += (sender, e) => SmokeDiagnostics.Fail("AppDomain.UnhandledException", e.ExceptionObject as Exception ?? new Exception("Native unhandled exception"));
        TaskScheduler.UnobservedTaskException += (sender, e) => SmokeDiagnostics.Fail("TaskScheduler.UnobservedTaskException", e.Exception);
        try
        {
            SmokeDiagnostics.Inventory();
            WinRT.ComWrappersSupport.InitializeComWrappers();
            SmokeDiagnostics.Record("Application.Start.before");
            Application.Start(p =>
            {
                SmokeDiagnostics.Record("Application.Start.callback");
                SynchronizationContext.SetSynchronizationContext(new DispatcherQueueSynchronizationContext(DispatcherQueue.GetForCurrentThread()));
                _ = new App();
            });
            SmokeDiagnostics.Record("Application.Start.returned");
        }
        catch (Exception e) { SmokeDiagnostics.Fail("Program.Main.failed", e); throw; }
    }
}
