using System.Reflection;
using System.Text.Json;
using System.Text.Json.Nodes;
namespace Vantage.Core;
public static class PlotText
{
    static readonly Dictionary<string, string> English = Load();
    static Dictionary<string, string> Load()
    {
        using var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("Vantage.Core.Resources.plot-en.json");
        return stream is null ? [] : JsonSerializer.Deserialize<Dictionary<string, string>>(stream) ?? [];
    }
    public static string Translate(string value, bool english) => english && English.TryGetValue(value, out var translated) ? translated : value;
    public static JsonElement Localize(JsonElement value, bool english)
    {
        if (!english || value.ValueKind == JsonValueKind.Undefined) return value;
        JsonNode? Walk(JsonNode? node)
        {
            if (node is JsonValue text && text.TryGetValue<string>(out var str)) return JsonValue.Create(Translate(str, true));
            if (node is JsonArray array) return new JsonArray(array.Select(Walk).ToArray());
            if (node is JsonObject obj) { var result = new JsonObject(); foreach (var p in obj) result[p.Key] = Walk(p.Value); return result; }
            return node?.DeepClone();
        }
        return JsonSerializer.SerializeToElement(Walk(JsonNode.Parse(value.GetRawText())), JsonData.Options);
    }
}
