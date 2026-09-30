using System.Text;
using System.Text.Json;
namespace Vantage.Windows.Platform;

// Explicit smoke invocations only. Never writes request bodies, configuration, credentials or user content.
internal static class SmokeDiagnostics
{
    static readonly object Gate = new();
    static readonly string? ReportPath = ResolveReport();
    static string? ResolveReport()
    {
        var args = Environment.GetCommandLineArgs(); var index = Array.IndexOf(args, "--smoke-test");
        return index >= 0 && index + 1 < args.Length ? Path.GetFullPath(args[index + 1]) : null;
    }
    public static void Record(string phase, Exception? error = null)
    {
        if (ReportPath is null) return;
        try
        {
            lock (Gate)
            {
                Directory.CreateDirectory(Path.GetDirectoryName(ReportPath)!);
                var path = ReportPath + ".startup.log";
                if (File.Exists(path) && new FileInfo(path).Length >= 32 * 1024) return;
                var text = $"{DateTimeOffset.UtcNow:O} {phase}";
                if (error is not null) text += $"\n{error.GetType().FullName} 0x{error.HResult:x8}: {error.Message}\n{error.StackTrace}";
                if (text.Length > 6000) text = text[..6000];
                File.AppendAllText(path, text + "\n", Encoding.UTF8);
            }
        }
        catch { /* Diagnostics must not replace the original failure. */ }
    }
    public static void Fail(string phase, Exception error)
    {
        Record(phase, error);
        if (ReportPath is null) return;
        try
        {
            var message = $"{phase}: {error.GetType().Name} 0x{error.HResult:x8}: {error.Message}";
            if (message.Length > 1500) message = message[..1500];
            File.WriteAllText(ReportPath, JsonSerializer.Serialize(new { success = false, pages = Array.Empty<object>(), errors = new[] { message }, phase }));
        }
        catch { }
    }
    public static void Inventory()
    {
        if (ReportPath is null) return;
        foreach (var name in new[] { "resources.pri", "Microsoft.WindowsAppRuntime.pri", "Microsoft.UI.Xaml.dll", "Microsoft.WindowsAppRuntime.Bootstrap.dll", "Microsoft.WindowsAppRuntime.dll", "Vantage.Windows.dll", "App.xbf", "MainWindow.xbf", "Assets/Vantage.ico" })
        {
            var path = Path.Combine(AppContext.BaseDirectory, name);
            Record($"asset {name}: {(File.Exists(path) ? new FileInfo(path).Length.ToString() : "missing")}");
        }
    }
}
