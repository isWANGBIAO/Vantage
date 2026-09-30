using Windows.Media.Capture;
using Windows.Media.MediaProperties;
using Windows.Storage;
namespace Vantage.Windows.Platform;
public sealed class VoiceRecorder : IAsyncDisposable
{
    MediaCapture? capture; string? path;
    public bool IsRecording { get; private set; }
    public async Task StartAsync()
    {
        if (IsRecording) return;
        var directory = Path.Combine(BackendHost.DataRoot, "runtime", "native-audio"); Directory.CreateDirectory(directory);
        path = Path.Combine(directory, $"voice-{Guid.NewGuid():N}.m4a");
        await File.WriteAllBytesAsync(path, []);
        try
        {
            capture = new MediaCapture();
            await capture.InitializeAsync(new MediaCaptureInitializationSettings { StreamingCaptureMode = StreamingCaptureMode.Audio });
            await capture.StartRecordToStorageFileAsync(MediaEncodingProfile.CreateM4a(AudioEncodingQuality.Auto), await StorageFile.GetFileFromPathAsync(path));
            IsRecording = true;
        }
        catch { await DisposeAsync(); throw; }
    }
    public async Task<string> StopAsync()
    {
        if (capture is null || !IsRecording || path is null) throw new InvalidOperationException("Recording is not active.");
        await capture.StopRecordAsync(); IsRecording = false; return path;
    }
    public async ValueTask DisposeAsync()
    {
        if (IsRecording && capture is not null) { try { await capture.StopRecordAsync(); } catch { } }
        IsRecording = false; capture?.Dispose(); capture = null;
        if (path is not null) { try { File.Delete(path); } catch (IOException) { } path = null; }
    }
}
