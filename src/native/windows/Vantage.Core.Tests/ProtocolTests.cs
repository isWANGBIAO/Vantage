using System.Net;
using System.Text;
using System.Text.Json;
using Vantage.Core;
using Xunit;
namespace Vantage.Core.Tests;

public class ProtocolTests
{
    [Theory]
    [InlineData("http://example.com")][InlineData("http://127.0.0.1@evil.test")][InlineData("file:///etc/passwd")]
    [InlineData("http://localhost?token=secret")][InlineData("http://localhost#x")][InlineData("http://192.168.1.5")]
    public void RejectUnsafeBackend(string url) => Assert.Throws<ArgumentException>(() => new BackendAddress(url));
    [Theory][InlineData("http://127.0.0.1:8000")][InlineData("https://localhost/proxy")][InlineData("http://[::1]:8000")]
    public void AcceptLoopback(string url) => Assert.NotNull(new BackendAddress(url));
    [Fact] public void PreserveProxyPrefix() => Assert.Equal("https://localhost/proxy/api/v1/settings", new BackendAddress("https://localhost/proxy").Endpoint("/api/v1/settings").AbsoluteUri);
    [Fact] public void RejectResourceEscape() => Assert.Throws<ArgumentException>(() => new BackendAddress("https://localhost/proxy").Endpoint("/../secret"));
    [Fact] public void ExplicitAddressWins() => Assert.Equal(9000, BackendAddress.Resolve("http://localhost:9000", _ => "bad").BaseUri.Port);
    [Fact] public async Task ReadUtf8SplitAndFinalLine()
    {
        var data = Encoding.UTF8.GetBytes("{\"log\":\"你好\"}\r\n\n{\"done\":true}");
        var lines = new List<string>();
        await foreach (var line in Ndjson.ReadAsync(new ChunkStream(data))) lines.Add(line);
        Assert.Equal(2, lines.Count); Assert.Contains("你好", lines[0]);
    }
    [Fact] public async Task RejectOversizedLine()
    {
        await Assert.ThrowsAsync<InvalidDataException>(async () => { await foreach (var _ in Ndjson.ReadAsync(new MemoryStream(new byte[Ndjson.MaxLineBytes + 1]))) { } });
    }
    [Fact] public void ChatParsesWireProtocolAndRequiresDone()
    {
        var state = new ChatStreamState(); state.Apply(new(Log: "STREAM_CONTENT:\"Hello \\" + "nworld\""));
        Assert.Contains("Hello", state.Content); Assert.Throws<InvalidDataException>(state.RequireSuccess);
        state.Apply(new(Done: true)); state.RequireSuccess();
    }
    [Fact] public void ErrorCannotBecomeSuccess()
    {
        var state = new ChatStreamState(); state.Apply(new(Log: "STREAM_ERROR:\"failure\"")); state.Apply(new(Done: true));
        Assert.Throws<InvalidDataException>(state.RequireSuccess);
    }
    [Fact] public void CompletionRequiresFullSavedPlan()
    {
        var job = new PlanJob("x", "succeeded", "manual", new(), new("done", 1), new(true, new("a"), new(""), "2026-01-01", "x.json", null), null, 1, false);
        Assert.Throws<InvalidDataException>(() => JobObserver.ValidateTerminal(job));
    }
    [Fact] public async Task MutationIsNeverAutomaticallyRetried()
    {
        var calls = 0;
        using var api = new ApiClient(new("http://localhost"), new Handler(_ => { calls++; return new(HttpStatusCode.ServiceUnavailable); }));
        await Assert.ThrowsAsync<ApiException>(() => api.CreateJobAsync(new())); Assert.Equal(1, calls);
    }
    [Fact] public async Task ClearChatUsesDeleteAndReturnedState()
    {
        using var api = new ApiClient(new("http://localhost"), new Handler(r => {
            Assert.Equal(HttpMethod.Delete, r.Method); Assert.Equal("/api/v1/chat/context", r.RequestUri!.AbsolutePath);
            return Json("{\"context_version\":\"new\",\"base_context_version\":\"base\",\"messages\":[],\"has_action_plan_context\":true}");
        }));
        var result = await api.ClearChatAsync(); Assert.Empty(result.Messages); Assert.Equal("new", result.ContextVersion);
    }
    [Fact] public async Task LostJobDoesNotResubmit()
    {
        using var api = new ApiClient(new("http://localhost"), new Handler(r => { Assert.Equal(HttpMethod.Get, r.Method); return new(HttpStatusCode.NotFound); }));
        await Assert.ThrowsAsync<JobLostException>(() => new JobObserver(api).ObserveAsync("old", null, null, default));
    }
    [Fact] public async Task MjpegHandlesChunkBoundaries()
    {
        var frames = new List<byte[]>(); await Mjpeg.ReadAsync(new ChunkStream([1, 0xff, 0xd8, 3, 0xff, 0xd9, 13, 10]), bytes => { frames.Add(bytes); return Task.CompletedTask; }, default);
        Assert.Single(frames); Assert.Equal(new byte[] { 0xff, 0xd8, 3, 0xff, 0xd9 }, frames[0]);
    }
    static HttpResponseMessage Json(string value) => new(HttpStatusCode.OK) { Content = new StringContent(value, Encoding.UTF8, "application/json") };
    sealed class Handler(Func<HttpRequestMessage, HttpResponseMessage> action) : HttpMessageHandler
    { protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct) => Task.FromResult(action(request)); }
    sealed class ChunkStream(byte[] bytes) : MemoryStream(bytes)
    { public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default) => base.ReadAsync(buffer[..Math.Min(1, buffer.Length)], cancellationToken); }
}
