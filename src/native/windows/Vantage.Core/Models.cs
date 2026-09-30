using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

namespace Vantage.Core;

public sealed record Capabilities(string ApiVersion, string Service)
{
    [JsonPropertyName("capabilities")] public string[] Features { get; init; } = [];
}
public sealed record PlanSection(string Body);
public sealed record PlanResult(bool Exists, PlanSection? Analysis, PlanSection? Plan, string? Date, string? Filename, JsonElement? Meta, string? Error = null, JsonElement? Id = null)
{
    public bool IsComplete => Exists && string.IsNullOrEmpty(Error) && !string.IsNullOrWhiteSpace(Analysis?.Body) && !string.IsNullOrWhiteSpace(Plan?.Body);
}
public sealed record JobRequest(string? Model = null, string? ProviderRoute = null, string? ReasoningEffort = null,
    string? ServiceTier = null, bool ReplaceToday = false, bool WaitForProviderReady = false);
public sealed record JobError(string Code, string Message);
public sealed record JobProgress(string Phase, int EventsReceived);
public sealed record PlanJob(string Id, string Status, string Trigger, JobRequest Request, JobProgress Progress,
    PlanResult? Result, JobError? Error, long EventCursor, bool Reused)
{
    public bool IsTerminal => Status is "succeeded" or "failed" or "cancelled";
}
public sealed record JobsResponse(PlanJob[] Jobs, PlanJob? Active);
public sealed record StreamEvent(long Sequence = 0, string? Log = null, string? Error = null, string? ErrorCode = null,
    bool Done = false, string? JobStatus = null, bool Truncated = false, bool EventTruncated = false, long? Cursor = null);
public sealed record ChatMessage(string Role, string Content);
public sealed record ChatContext(string ContextVersion, string BaseContextVersion, bool HasActionPlanContext,
    ChatMessage[] Messages, JsonElement? Stats, string? PreferredModel, string? PreferredProviderRoute);
public sealed record ChatRequest(string Message, string? Model = null, string? ProviderRoute = null,
    string? ReasoningEffort = null, string? ServiceTier = null, string? ClientSentAt = null);
public sealed record OnboardingState(bool Completed,
    [property: JsonPropertyName("launchAtLogin")] bool LaunchAtLogin,
    [property: JsonPropertyName("displayLanguage")] string DisplayLanguage,
    [property: JsonPropertyName("providerConfigured")] bool ProviderConfigured,
    [property: JsonPropertyName("migrationCompleted")] bool MigrationCompleted,
    [property: JsonPropertyName("legacyRoot")] string? LegacyRoot);
public sealed record SettingsState(JsonObject Settings, JsonObject Provider, JsonObject Migration, Dictionary<string, string> RuntimePaths);
public sealed record SystemStatus(bool CameraOnline, bool ShowPersonBox, bool CameraFrameAvailable, bool CameraFrameDark);
public sealed record SystemStatistics(double CpuUsage, double MemoryUsedGb, double MemoryTotalGb, double MemoryPercent,
    double DiskFreeGb, double StorageUsedMb, bool StorageScanTruncated);
public sealed record LatestMedia(string? Photo, string? Screenshot);
public sealed record LogsResponse(string[] Logs);
public sealed record TranscriptionResponse(string? Transcription);
public sealed record ProjectTask(string Project, string Task, string Status);
public sealed record ProjectTasks(ProjectTask[] Completed, ProjectTask[] Pending);
public sealed record ProjectStats(int TotalTasks, int CompletedTasks, double CompletionRate);
public sealed record ProjectCommit(string Hash, string Date, string Message);
public sealed record ProjectsResponse(ProjectTasks Tasks, ProjectCommit[] Commits, ProjectStats Stats);
public sealed record ChartDefinition(string Id, string Title, string? Subtitle, string? Description, JsonElement Option,
    JsonElement Summary, string? Status, string? Message, bool Empty = false, string? Error = null, string? Formatter = null);
public sealed record PlotsResponse(ChartDefinition[] Charts, JsonElement Warnings);
public sealed record FaceProgress(string Status, double Percent, string? Error);

public static class JsonData
{
    public static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        MaxDepth = 64
    };
    public static JsonElement Field(this JsonElement value, string name) => value.ValueKind == JsonValueKind.Object && value.TryGetProperty(name, out var item) ? item : default;
    public static string Text(this JsonElement value, string fallback = "") => value.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null ? fallback : value.ValueKind == JsonValueKind.String ? value.GetString() ?? fallback : value.ToString();
    public static double? Number(this JsonElement value) => value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var n) && double.IsFinite(n) ? n : null;
    public static IEnumerable<JsonElement> Items(this JsonElement value) => value.ValueKind == JsonValueKind.Array ? value.EnumerateArray() : [];
    public static string String(this JsonObject value, string key, string fallback = "") => value[key]?.GetValue<string>() ?? fallback;
    public static bool Bool(this JsonObject value, string key) => value[key]?.GetValue<bool>() ?? false;
    // Chart option member names (xAxis, yAxisIndex) belong to the ECharts data contract, not API DTO snake_case.
    public static JsonElement ChartElement(object value) => JsonSerializer.SerializeToElement(value, new JsonSerializerOptions(Options) { PropertyNamingPolicy = null });
    public static JsonElement Element(object value) => JsonSerializer.SerializeToElement(value, Options);
}
