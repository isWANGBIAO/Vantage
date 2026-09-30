using System.Net;
using System.Text;
using System.Text.Json;
namespace Vantage.Core;

public sealed class JobLostException() : Exception("The backend restarted or no longer retains this job. Reload today's plan and the job list.");

public sealed class JobObserver(ApiClient api)
{
    public async Task<PlanJob> ObserveAsync(string id, Action<PlanJob>? snapshot, Action<StreamEvent>? progress, CancellationToken ct)
    {
        long cursor = 0; var delay = 300;
        while (true)
        {
            ct.ThrowIfCancellationRequested();
            try
            {
                var job = await api.JobAsync(id, ct);
                snapshot?.Invoke(job);
                if (job.IsTerminal) return ValidateTerminal(job);
                using var observation = CancellationTokenSource.CreateLinkedTokenSource(ct);
                observation.CancelAfter(TimeSpan.FromSeconds(90));
                await foreach (var item in api.JobEventsAsync(id, cursor, observation.Token))
                {
                    if (item.Truncated || item.EventTruncated)
                    {
                        cursor = Math.Max(cursor, item.Cursor ?? item.Sequence);
                        // A missing fragment is never concatenated into a successful result.
                        progress?.Invoke(item);
                        break;
                    }
                    if (item.Sequence <= cursor) continue;
                    cursor = item.Sequence; progress?.Invoke(item);
                    if (item.Done || item.Error is not null || item.JobStatus is "cancelled" or "failed" or "succeeded") break;
                }
                // EOF (even with content) is not completion. Consult the authoritative job.
                job = await api.JobAsync(id, ct); snapshot?.Invoke(job);
                if (job.IsTerminal) return ValidateTerminal(job);
                delay = 300;
            }
            catch (ApiException e) when (e.Status == HttpStatusCode.NotFound) { throw new JobLostException(); }
            catch (ApiException e) when ((int)e.Status >= 500) { delay = Math.Min(delay * 2, 5000); }
            catch (OperationCanceledException) when (!ct.IsCancellationRequested) { delay = Math.Min(delay * 2, 5000); }
            catch (HttpRequestException) { delay = Math.Min(delay * 2, 5000); }
            catch (IOException) { delay = Math.Min(delay * 2, 5000); }
            await Task.Delay(delay, ct);
        }
    }
    public static PlanJob ValidateTerminal(PlanJob job)
    {
        if (job.Status == "succeeded" && (job.Error is not null || job.Result?.IsComplete != true))
            throw new InvalidDataException("Backend reported success without a complete saved action plan.");
        return job;
    }
}

public sealed class ChatStreamState
{
    const int MaxText = 4 * 1024 * 1024;
    readonly StringBuilder content = new();
    readonly StringBuilder thinking = new();
    public string Content => content.ToString();
    public string Thinking => thinking.ToString();
    public string? Error { get; private set; }
    public bool Done { get; private set; }
    public JsonElement? Stats { get; private set; }
    public void Apply(StreamEvent item)
    {
        if (item.Error is not null) Error = item.Error;
        if (item.Done) Done = true;
        var log = item.Log ?? "";
        foreach (var prefix in new[] { "STREAM_CONTENT:", "STREAM_THINKING:", "STREAM_ERROR:", "STATS_JSON:" })
        {
            if (!log.StartsWith(prefix, StringComparison.Ordinal)) continue;
            var raw = log[prefix.Length..];
            if (prefix == "STATS_JSON:") { Stats = JsonSerializer.Deserialize<JsonElement>(raw); break; }
            string text;
            try { text = JsonSerializer.Deserialize<string>(raw) ?? ""; } catch (JsonException) { text = raw; }
            if (prefix == "STREAM_ERROR:") Error = text;
            else
            {
                var target = prefix == "STREAM_CONTENT:" ? content : thinking;
                if (target.Length + text.Length > MaxText) throw new InvalidDataException("Chat output exceeds safe display size.");
                target.Append(text);
            }
            break;
        }
    }
    public void RequireSuccess()
    {
        if (Error is not null) throw new InvalidDataException("Chat generation failed. Reload the saved conversation and check System Logs.");
        if (!Done) throw new InvalidDataException("Chat stream ended before its completion event. The saved conversation will be reloaded.");
    }
}
