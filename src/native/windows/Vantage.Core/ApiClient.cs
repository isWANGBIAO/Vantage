using System.Net;
using System.Net.Http.Json;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Vantage.Core;

public sealed class ApiException(HttpStatusCode status) : Exception($"Backend request failed (HTTP {(int)status}). Check System Logs for details.")
{
    public HttpStatusCode Status { get; } = status;
}

public sealed class ApiClient : IDisposable
{
    readonly HttpClient http;
    public BackendAddress Address { get; }
    public ApiClient(BackendAddress address, HttpMessageHandler? handler = null)
    {
        Address = address;
        http = new HttpClient(handler ?? new HttpClientHandler { AllowAutoRedirect = false, UseProxy = false }) { Timeout = Timeout.InfiniteTimeSpan };
    }
    public void Dispose() => http.Dispose();
    public async Task<T> SendAsync<T>(HttpMethod method, string path, object? body = null, CancellationToken ct = default)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeout.CancelAfter(TimeSpan.FromSeconds(90));
        using var request = new HttpRequestMessage(method, Address.Endpoint(path));
        if (path == "/api/v1/media/open-folder" && method == HttpMethod.Post) request.Headers.Add("X-Vantage-Intent", "open-folder");
        if (body is not null) request.Content = JsonContent.Create(body, options: JsonData.Options);
        using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, timeout.Token);
        if (!response.IsSuccessStatusCode) throw new ApiException(response.StatusCode);
        await using var stream = await response.Content.ReadAsStreamAsync(timeout.Token);
        var bytes = await ReadBoundedAsync(stream, 32 * 1024 * 1024, timeout.Token);
        return JsonSerializer.Deserialize<T>(bytes, JsonData.Options) ?? throw new InvalidDataException("Empty backend response.");
    }
    public Task<T> GetAsync<T>(string path, CancellationToken ct = default) => SendAsync<T>(HttpMethod.Get, path, ct: ct);
    public Task<JsonElement> PostAsync(string path, object? body = null, CancellationToken ct = default) => SendAsync<JsonElement>(HttpMethod.Post, path, body ?? new {}, ct);
    public Task<SystemStatus> StatusAsync(CancellationToken ct = default) => GetAsync<SystemStatus>("/api/v1/system/status", ct);
    public async Task VerifyAsync(CancellationToken ct = default)
    {
        var caps = await GetAsync<Capabilities>("/api/v1/capabilities", ct);
        if (caps.Service != "vantage" || caps.ApiVersion?.Split('.')[0] != "1") throw new InvalidDataException("This client requires the Vantage v1 API.");
        await GetAsync<JsonElement>("/api/v1/operations", ct);
    }
    public async Task VerifySyntheticFixtureAsync(CancellationToken ct = default)
    {
        var marker = await GetAsync<JsonElement>("/__test__/requests", ct);
        if (marker.ValueKind != JsonValueKind.Array || !marker.Items().Any(entry => entry.Field("method").Text() == "GET" && entry.Field("path").Text() == "/__test__/requests"))
            throw new InvalidDataException("Smoke mode requires the isolated synthetic fixture server; no application data was read or changed.");
    }
    public Task<SettingsState> SettingsAsync(CancellationToken ct = default) => GetAsync<SettingsState>("/api/v1/settings", ct);
    public Task<SettingsState> UpdateSettingsAsync(JsonObject patch, CancellationToken ct = default) => SendAsync<SettingsState>(HttpMethod.Put, "/api/v1/settings", patch, ct);
    public Task<OnboardingState> OnboardingAsync(CancellationToken ct = default) => GetAsync<OnboardingState>("/api/v1/onboarding", ct);
    public Task<JsonElement> CompleteOnboardingAsync(JsonObject value, CancellationToken ct = default) => PostAsync("/api/v1/onboarding/complete", value, ct);
    public Task<PlanResult> PlanAsync(CancellationToken ct = default) => GetAsync<PlanResult>("/api/v1/action-plan/today", ct);
    public Task<JobsResponse> JobsAsync(CancellationToken ct = default) => GetAsync<JobsResponse>("/api/v1/action-plan/jobs", ct);
    public Task<PlanJob> CreateJobAsync(JobRequest request, CancellationToken ct = default) => SendAsync<PlanJob>(HttpMethod.Post, "/api/v1/action-plan/jobs", request, ct);
    public Task<PlanJob> JobAsync(string id, CancellationToken ct = default) => GetAsync<PlanJob>($"/api/v1/action-plan/jobs/{Uri.EscapeDataString(id)}", ct);
    public Task<PlanJob> CancelJobAsync(string id, CancellationToken ct = default) => SendAsync<PlanJob>(HttpMethod.Post, $"/api/v1/action-plan/jobs/{Uri.EscapeDataString(id)}/cancel", new {}, ct);
    public Task<ChatContext> ChatContextAsync(CancellationToken ct = default) => GetAsync<ChatContext>("/api/v1/chat/context", ct);
    public Task<ChatContext> ClearChatAsync(CancellationToken ct = default) => SendAsync<ChatContext>(HttpMethod.Delete, "/api/v1/chat/context", ct: ct);
    public IAsyncEnumerable<StreamEvent> ChatAsync(ChatRequest request, CancellationToken ct) => StreamAsync(HttpMethod.Post, "/api/v1/chat", request, ct);
    public IAsyncEnumerable<StreamEvent> JobEventsAsync(string id, long after, CancellationToken ct) => StreamAsync(HttpMethod.Get, $"/api/v1/action-plan/jobs/{Uri.EscapeDataString(id)}/events?after={after}", null, ct);
    public async IAsyncEnumerable<StreamEvent> StreamAsync(HttpMethod method, string path, object? body, [EnumeratorCancellation] CancellationToken ct)
    {
        using var request = new HttpRequestMessage(method, Address.Endpoint(path));
        if (body is not null) request.Content = JsonContent.Create(body, options: JsonData.Options);
        using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, ct);
        if (!response.IsSuccessStatusCode) throw new ApiException(response.StatusCode);
        await using var stream = await response.Content.ReadAsStreamAsync(ct);
        await foreach (var line in Ndjson.ReadAsync(stream, ct))
            yield return JsonSerializer.Deserialize<StreamEvent>(line, JsonData.Options) ?? throw new InvalidDataException("Invalid event.");
    }
    public async Task<byte[]> DownloadAsync(string path, CancellationToken ct = default)
    {
        using var response = await http.GetAsync(Address.Endpoint(path), HttpCompletionOption.ResponseHeadersRead, ct);
        if (!response.IsSuccessStatusCode) throw new ApiException(response.StatusCode);
        await using var stream = await response.Content.ReadAsStreamAsync(ct);
        return await ReadBoundedAsync(stream, 64 * 1024 * 1024, ct);
    }
    public async Task StreamCameraAsync(Func<byte[], Task> onFrame, CancellationToken ct)
    {
        using var response = await http.GetAsync(Address.Endpoint("/api/v1/camera/stream"), HttpCompletionOption.ResponseHeadersRead, ct);
        if (!response.IsSuccessStatusCode) throw new ApiException(response.StatusCode);
        await using var stream = await response.Content.ReadAsStreamAsync(ct);
        await Mjpeg.ReadAsync(stream, onFrame, ct);
    }
    public async Task<TranscriptionResponse> TranscribeAsync(Stream audio, string filename, CancellationToken ct = default)
    {
        using var content = new MultipartFormDataContent();
        content.Add(new StreamContent(audio), "file", Path.GetFileName(filename));
        using var response = await http.PostAsync(Address.Endpoint("/api/v1/media/transcribe"), content, ct);
        if (!response.IsSuccessStatusCode) throw new ApiException(response.StatusCode);
        return await response.Content.ReadFromJsonAsync<TranscriptionResponse>(JsonData.Options, ct) ?? throw new InvalidDataException("Empty transcription.");
    }
    internal static async Task<byte[]> ReadBoundedAsync(Stream stream, int max, CancellationToken ct)
    {
        using var result = new MemoryStream(); var buffer = new byte[8192]; int count;
        while ((count = await stream.ReadAsync(buffer, ct)) != 0)
        {
            if (result.Length + count > max) throw new InvalidDataException("Backend response exceeds the safe size limit.");
            result.Write(buffer, 0, count);
        }
        return result.ToArray();
    }
}

public static class Ndjson
{
    public const int MaxLineBytes = 1024 * 1024;
    public static async IAsyncEnumerable<string> ReadAsync(Stream stream, [EnumeratorCancellation] CancellationToken ct = default)
    {
        var buffer = new byte[8192]; using var line = new MemoryStream(); int count;
        var utf8 = new UTF8Encoding(false, true);
        while ((count = await stream.ReadAsync(buffer, ct)) > 0)
        {
            for (var i = 0; i < count; i++)
            {
                if (buffer[i] == 10)
                {
                    var text = utf8.GetString(line.ToArray()).TrimEnd('\r'); line.SetLength(0);
                    if (!string.IsNullOrWhiteSpace(text)) yield return text;
                }
                else
                {
                    if (line.Length >= MaxLineBytes) throw new InvalidDataException("NDJSON event exceeds 1 MiB.");
                    line.WriteByte(buffer[i]);
                }
            }
        }
        if (line.Length > 0) { var text = utf8.GetString(line.ToArray()).TrimEnd('\r'); if (!string.IsNullOrWhiteSpace(text)) yield return text; }
    }
}

public static class Mjpeg
{
    // Parse JPEG markers, not MIME boundaries: backend frames contain normal JPEG SOI/EOI pairs.
    public static async Task ReadAsync(Stream stream, Func<byte[], Task> onFrame, CancellationToken ct)
    {
        var buffer = new byte[16384]; using var frame = new MemoryStream(); var previous = -1; var inside = false; int count;
        while ((count = await stream.ReadAsync(buffer, ct)) > 0)
        {
            foreach (var b in buffer.Take(count))
            {
                if (!inside && previous == 0xff && b == 0xd8) { inside = true; frame.SetLength(0); frame.WriteByte(0xff); }
                if (inside)
                {
                    if (frame.Length >= 8 * 1024 * 1024) throw new InvalidDataException("Camera frame exceeds safe size.");
                    frame.WriteByte(b);
                    if (previous == 0xff && b == 0xd9) { inside = false; await onFrame(frame.ToArray()); }
                }
                previous = b;
            }
        }
    }
}
