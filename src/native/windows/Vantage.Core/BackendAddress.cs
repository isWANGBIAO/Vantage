using System.Net;
using System.Text.RegularExpressions;
namespace Vantage.Core;

public sealed class BackendAddress
{
    public Uri BaseUri { get; }
    public bool CanLaunch => BaseUri.Scheme == "http" && BaseUri.AbsolutePath == "/";
    public BackendAddress(string value)
    {
        var rawAuthority = Regex.Match(value, @"^https?://(\[[^\]]+\]|[^/:?#]+)", RegexOptions.IgnoreCase).Groups[1].Value;
        if (value.Contains('\\') || value.Any(c => char.IsControl(c)) || !IsLoopback(rawAuthority) || !Uri.TryCreate(value, UriKind.Absolute, out var uri) || uri.Scheme is not ("http" or "https") ||
            uri.Port == 0 || !string.IsNullOrEmpty(uri.UserInfo) || !string.IsNullOrEmpty(uri.Query) || !string.IsNullOrEmpty(uri.Fragment) ||
            !(uri.Host.Equals("localhost", StringComparison.OrdinalIgnoreCase) || (IPAddress.TryParse(uri.DnsSafeHost.Trim('[', ']'), out var ip) && IPAddress.IsLoopback(ip))))
            throw new ArgumentException("Backend address must be loopback HTTP(S), without credentials, query or fragment.");
        BaseUri = new Uri(uri.AbsoluteUri.TrimEnd('/') + "/");
    }
    static bool IsLoopback(string host)
    {
        host = host.Trim('[', ']').ToLowerInvariant();
        if (host is "localhost" or "::1") return true;
        var octets = host.Split('.');
        return octets.Length == 4 && octets[0] == "127" && octets.All(x => Regex.IsMatch(x, @"^(0|[1-9]\d{0,2})$") && int.Parse(x) <= 255);
    }
    public static BackendAddress Resolve(string? explicitUrl = null, Func<string, string?>? env = null)
    {
        env ??= Environment.GetEnvironmentVariable;
        var url = explicitUrl ?? env("VANTAGE_BACKEND_URL");
        if (string.IsNullOrWhiteSpace(url))
        {
            var host = env("VANTAGE_BACKEND_HOST") ?? "127.0.0.1";
            var port = env("VANTAGE_BACKEND_PORT") ?? "8000";
            if (host.Contains(':') && !host.StartsWith('[')) host = $"[{host}]";
            url = $"http://{host}:{port}";
        }
        return new BackendAddress(url);
    }
    public Uri Endpoint(string path)
    {
        if (Regex.IsMatch(path.Split('?')[0], @"(?:^|/)\.{1,2}(?:/|$)|%(?:2e|2f|5c)", RegexOptions.IgnoreCase) || !path.StartsWith('/') || path.StartsWith("//") || path.Contains('\\') || path.Contains('#'))
            throw new ArgumentException("Expected a backend-relative path.");
        var uri = new Uri(BaseUri, path.TrimStart('/'));
        if (uri.GetLeftPart(UriPartial.Authority) != BaseUri.GetLeftPart(UriPartial.Authority) || !uri.AbsolutePath.StartsWith(BaseUri.AbsolutePath, StringComparison.Ordinal))
            throw new ArgumentException("Resource escapes the backend prefix.");
        return uri;
    }
}
