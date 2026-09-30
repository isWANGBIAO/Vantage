using Windows.Media.Capture;
using Windows.Media.MediaProperties;
using Windows.Storage;
namespace Vantage.Windows.Platform;
public sealed class VoiceRecorder : IAsyncDisposable
{
    readonly SemaphoreSlim gate = new(1, 1);
    MediaCapture? capture; string? path;
    public bool IsRecording { get; private set; }
    public async Task StartAsync()
    {
        await gate.WaitAsync();
        try
        {
            if (IsRecording) return;
            if (path is not null) { await CleanupAsync(); if (path is not null) throw new IOException("The previous recording is still in use."); }
            var directory = Path.Combine(Environment.GetEnvironmentVariable("VANTAGE_RUNTIME_DIR") ?? Path.Combine(BackendHost.DataRoot, "runtime"), "native-audio"); Directory.CreateDirectory(directory);
            path = Path.Combine(directory, $"voice-{Guid.NewGuid():N}.m4a"); await File.WriteAllBytesAsync(path, []);
            try
            {
                capture = new MediaCapture();
                await capture.InitializeAsync(new MediaCaptureInitializationSettings { StreamingCaptureMode = StreamingCaptureMode.Audio });
                await capture.StartRecordToStorageFileAsync(MediaEncodingProfile.CreateM4a(AudioEncodingQuality.Auto), await StorageFile.GetFileFromPathAsync(path)); IsRecording = true;
            }
            catch { await CleanupAsync(); throw; }
        }
        finally { gate.Release(); }
    }
    public async Task<string> StopAsync()
    {
        await gate.WaitAsync();
        try
        {
            if (capture is null || !IsRecording || path is null) throw new InvalidOperationException("Recording is not active.");
            await capture.StopRecordAsync(); IsRecording = false; return path;
        }
        finally { gate.Release(); }
    }
    async Task CleanupAsync()
    {
        if (IsRecording && capture is not null) { try { await capture.StopRecordAsync(); } catch { } }
        IsRecording = false; capture?.Dispose(); capture = null;
        if (path is not null) { try { File.Delete(path); path = null; } catch (IOException) { /* Retain ownership and retry after the upload stream closes. */ } }
    }
    public async ValueTask DisposeAsync() { await gate.WaitAsync(); try { await CleanupAsync(); } finally { gate.Release(); } }
}
