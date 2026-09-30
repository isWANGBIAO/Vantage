using System.Diagnostics;
using Vantage.Core;
namespace Vantage.Windows.Platform;

public sealed class BackendHost(ApiClient api) : IDisposable
{
    Process? owned;
    public bool OwnsProcess => owned is not null;
    public static string DataRoot => Environment.GetEnvironmentVariable("VANTAGE_DATA_DIR") ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Vantage");
    public async Task StartOrConnectAsync(bool connectOnly, CancellationToken ct)
    {
        try { using var probe = CancellationTokenSource.CreateLinkedTokenSource(ct); probe.CancelAfter(TimeSpan.FromSeconds(2)); await api.StatusAsync(probe.Token); await api.VerifyAsync(ct); return; }
        catch (HttpRequestException) { }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested) { }
        if (connectOnly || !api.Address.CanLaunch) throw new InvalidOperationException("Start the configured local backend, then reconnect. HTTPS and proxy prefixes require an already-running backend.");
        // An exclusive file handle is non-thread-affine and stays held through readiness.
        // The app itself is single-instance; this also serializes other native launchers.
        var runtime = Environment.GetEnvironmentVariable("VANTAGE_RUNTIME_DIR") ?? Path.Combine(DataRoot, "runtime");
        Directory.CreateDirectory(runtime);
        FileStream? gate = null;
        using var lockTimeout = CancellationTokenSource.CreateLinkedTokenSource(ct); lockTimeout.CancelAfter(TimeSpan.FromMinutes(3));
        while (gate is null)
        {
            lockTimeout.Token.ThrowIfCancellationRequested();
            try { gate = new FileStream(Path.Combine(runtime, "native-backend-launch.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None); }
            catch (IOException) { await Task.Delay(300, lockTimeout.Token); }
        }
        using var launchGate = gate;
        try { using var probe = CancellationTokenSource.CreateLinkedTokenSource(ct); probe.CancelAfter(TimeSpan.FromSeconds(2)); await api.StatusAsync(probe.Token); await api.VerifyAsync(ct); return; }
        catch (HttpRequestException) { }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested) { }
        var exe = Environment.GetEnvironmentVariable("VANTAGE_BACKEND_EXECUTABLE") ?? Path.Combine(AppContext.BaseDirectory, "backend-runtime", "VantageBackend", "VantageBackend.exe");
        if (!File.Exists(exe)) throw new FileNotFoundException("Bundled backend is missing. Build the native package with -BackendRuntime, or run the shared backend and reconnect.");
        Directory.CreateDirectory(DataRoot);
        var start = new ProcessStartInfo(exe) { UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = DataRoot };
        start.Environment["VANTAGE_APP_MODE"] = "packaged";
        start.Environment["VANTAGE_DATA_DIR"] = DataRoot;
        start.Environment["VANTAGE_BACKEND_URL"] = api.Address.BaseUri.ToString().TrimEnd('/');
        start.Environment["VANTAGE_BACKEND_HOST"] = api.Address.BaseUri.DnsSafeHost.Trim('[', ']');
        start.Environment["VANTAGE_BACKEND_PORT"] = api.Address.BaseUri.Port.ToString(System.Globalization.CultureInfo.InvariantCulture);
        start.Environment.Remove("VANTAGE_PROJECT_ROOT");
        owned = Process.Start(start) ?? throw new InvalidOperationException("Backend process could not start.");
        using var ready = CancellationTokenSource.CreateLinkedTokenSource(ct); ready.CancelAfter(TimeSpan.FromMinutes(2));
        while (true)
        {
            if (owned.HasExited) throw new InvalidOperationException("The backend exited during startup. Check the shared runtime logs.");
            try { using var probe = CancellationTokenSource.CreateLinkedTokenSource(ready.Token); probe.CancelAfter(TimeSpan.FromSeconds(2)); await api.StatusAsync(probe.Token); await api.VerifyAsync(ready.Token); return; }
            catch (HttpRequestException) { }
            catch (OperationCanceledException) when (!ready.IsCancellationRequested) { }
            await Task.Delay(500, ready.Token);
        }
    }
    public void Dispose()
    {
        if (owned is null) return;
        try { if (!owned.HasExited) { owned.Kill(entireProcessTree: true); owned.WaitForExit(5000); } } finally { owned.Dispose(); owned = null; }
    }
}
