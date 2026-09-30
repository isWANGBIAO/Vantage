using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Vantage.Core;
using Xunit;
namespace Vantage.Core.Tests;
public class WorkflowTests
{
    static PlanJob Job(string status = "running", PlanResult? result = null, JobError? error = null) => new("job-1", status, "manual", new(), new("analysis", 1), result, error, 2, false);
    static PlanResult Complete() => new(true, new("analysis"), new("plan"), "2026-01-01", "test.json", null);
    static HttpResponseMessage Json(object value) => Text(JsonSerializer.Serialize(value, JsonData.Options), "application/json");
    static HttpResponseMessage Text(string value, string type = "application/x-ndjson") => new(HttpStatusCode.OK) { Content = new StringContent(value, Encoding.UTF8, type) };
    sealed class Handler(Func<HttpRequestMessage, Task<HttpResponseMessage>> action) : HttpMessageHandler
    { protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct) => action(request); }

    [Fact] public async Task EofReconnectsWithCursorAndDeduplicates()
    {
        int streams = 0; var received = new List<long>();
        using var api = new ApiClient(new("http://localhost"), new Handler(r =>
        {
            if (r.RequestUri!.AbsolutePath.EndsWith("/events"))
            {
                streams++; Assert.Equal(streams == 1 ? "?after=0" : "?after=1", r.RequestUri.Query);
                return Task.FromResult(streams == 1 ? Text("{\"sequence\":1,\"log\":\"first\"}\n") : Text("{\"sequence\":1,\"log\":\"duplicate\"}\n{\"sequence\":2,\"done\":true,\"job_status\":\"succeeded\"}\n"));
            }
            return Task.FromResult(Json(streams >= 2 ? Job("succeeded", Complete()) : Job()));
        }));
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var result = await new JobObserver(api).ObserveAsync("job-1", null, e => received.Add(e.Sequence), timeout.Token);
        Assert.Equal("succeeded", result.Status); Assert.Equal(new long[] { 1, 2 }, received); Assert.Equal(2, streams);
    }
    [Fact] public async Task TruncationReloadsAuthoritativeResult()
    {
        var streamed = false; var truncated = false;
        using var api = new ApiClient(new("http://localhost"), new Handler(r =>
        {
            if (r.RequestUri!.AbsolutePath.EndsWith("events")) { streamed = true; return Task.FromResult(Text("{\"truncated\":true,\"cursor\":120}\n")); }
            return Task.FromResult(Json(streamed ? Job("succeeded", Complete()) : Job()));
        }));
        var result = await new JobObserver(api).ObserveAsync("job-1", null, e => truncated = e.Truncated, default);
        Assert.True(truncated); Assert.Equal("plan", result.Result!.Plan!.Body);
    }
    [Fact] public void ErrorMarkedResultCannotCountAsSuccess()
    {
        Assert.Throws<InvalidDataException>(() => JobObserver.ValidateTerminal(Job("succeeded", Complete() with { Error = "failed" })));
        Assert.Throws<InvalidDataException>(() => JobObserver.ValidateTerminal(Job("succeeded", Complete(), new("failed", "failed"))));
    }
    [Fact] public async Task ObservationCancellationDoesNotCancelServerJob()
    {
        var requests = new List<HttpMethod>();
        using var api = new ApiClient(new("http://localhost"), new Handler(r => { requests.Add(r.Method); return Task.FromResult(r.RequestUri!.AbsolutePath.EndsWith("events") ? Text("") : Json(Job())); }));
        using var cts = new CancellationTokenSource(TimeSpan.FromMilliseconds(80));
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => new JobObserver(api).ObserveAsync("job-1", null, null, cts.Token));
        Assert.All(requests, method => Assert.Equal(HttpMethod.Get, method));
    }
    [Fact] public async Task CancelIsExplicitPost()
    {
        using var api = new ApiClient(new("http://localhost"), new Handler(r => { Assert.Equal(HttpMethod.Post, r.Method); Assert.EndsWith("/job-1/cancel", r.RequestUri!.AbsolutePath); return Task.FromResult(Json(Job("cancelling"))); }));
        Assert.Equal("cancelling", (await api.CancelJobAsync("job-1")).Status);
    }
    [Fact] public async Task OpeningMediaFolderCarriesLocalIntent()
    {
        using var api = new ApiClient(new("http://localhost"), new Handler(async r =>
        {
            Assert.Equal("open-folder", Assert.Single(r.Headers.GetValues("X-Vantage-Intent")));
            Assert.Contains("photo", await r.Content!.ReadAsStringAsync()); return Json(new { success = true });
        }));
        await api.PostAsync("/api/v1/media/open-folder", new { type = "photo" });
    }
    [Fact] public async Task PartialSettingsUpdateDoesNotInventProviders()
    {
        using var api = new ApiClient(new("http://localhost"), new Handler(async r =>
        {
            Assert.Equal(HttpMethod.Put, r.Method); var body = await r.Content!.ReadAsStringAsync(); Assert.DoesNotContain("provider_config", body);
            return Json(new { settings = new { display_language = "en-US" }, provider = new {}, migration = new {}, runtime_paths = new {} });
        }));
        await api.UpdateSettingsAsync(new JsonObject { ["display_language"] = "en-US" });
    }
    [Fact] public async Task TranscriptionUsesActualResponseFieldAndMultipartName()
    {
        using var api = new ApiClient(new("http://localhost"), new Handler(async r =>
        {
            Assert.Equal("/api/v1/media/transcribe", r.RequestUri!.AbsolutePath);
            Assert.Equal("multipart/form-data", r.Content!.Headers.ContentType!.MediaType);
            Assert.Contains("name=file", (await r.Content.ReadAsStringAsync()).Replace("\"", ""));
            return Json(new { transcription = "Synthetic transcript" });
        }));
        Assert.Equal("Synthetic transcript", (await api.TranscribeAsync(new MemoryStream([1, 2]), "audio.wav")).Transcription);
    }
    [Theory][InlineData("http://127.1")][InlineData("http://2130706433")][InlineData("http://127.0.0.1:0")][InlineData("http://localhost\\evil")][InlineData("http://localhost\n")]
    public void RejectNonCanonicalAddress(string url) => Assert.Throws<ArgumentException>(() => new BackendAddress(url));
    [Theory][InlineData("/%2e%2e/secret")][InlineData("//evil.test")][InlineData("/api/../settings")][InlineData("/api/%2fsecret")]
    public void RejectEncodedResourceTraversal(string path) => Assert.Throws<ArgumentException>(() => new BackendAddress("http://localhost").Endpoint(path));
    [Fact] public async Task IncompatibleApiFailsBeforeUsingSettings()
    {
        using var api = new ApiClient(new("http://localhost"), new Handler(_ => Task.FromResult(Json(new { api_version = "2.0", service = "vantage" }))));
        await Assert.ThrowsAsync<InvalidDataException>(() => api.VerifyAsync());
    }
    [Fact] public async Task ErrorMessagesNeverReflectResponseSecrets()
    {
        using var api = new ApiClient(new("http://localhost"), new Handler(_ => Task.FromResult(new HttpResponseMessage(HttpStatusCode.BadRequest) { Content = new StringContent("api_key=highly-sensitive-test-value") })));
        var error = await Assert.ThrowsAsync<ApiException>(() => api.PostAsync("/api/v1/models/discover")); Assert.DoesNotContain("sensitive", error.Message);
    }
}
