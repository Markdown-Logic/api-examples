using System.Globalization;
using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

/// <summary>An actionable message that can be printed without exposing API payloads.</summary>
sealed class ExampleError(string message) : Exception(message)
{
}

/// <summary>Supplies the shared HTTP behavior needed by these six examples.</summary>
/// <remarks>Writes are single-attempt. Only rate-limited GET requests are retried.</remarks>
sealed class MdlApi : IDisposable
{
    readonly HttpClient http = new(new HttpClientHandler { AllowAutoRedirect = false })
    {
        // A per-attempt token also covers body consumption below.
        Timeout = Timeout.InfiniteTimeSpan
    };
    readonly string origin = ReadOrigin("MDLOGIC_API_ORIGIN", "https://api.markdownlogic.com");
    string? token = Environment.GetEnvironmentVariable("MDLOGIC_TOKEN");

    public static string Required(string name)
    {
        return Environment.GetEnvironmentVariable(name) is { Length: > 0 } value
            ? value
            : throw new ExampleError("Missing " + name + ".");
    }

    static string ReadOrigin(string name, string fallback)
    {
        string value = Environment.GetEnvironmentVariable(name) ?? fallback;
        if (!Uri.TryCreate(value, UriKind.Absolute, out var url)
            || url.UserInfo.Length != 0 || url.Query.Length != 0 || url.Fragment.Length != 0
            || url.AbsolutePath != "/" || url.Host.Length == 0
            || (url.Scheme != "https" && !(url.Scheme == "http"
                && new[] { "localhost", "127.0.0.1", "[::1]", "::1" }.Contains(url.Host))))
        {
            throw new ExampleError(name + " must be an HTTPS origin (literal loopback HTTP is allowed for local tests).");
        }

        return url.GetLeftPart(UriPartial.Authority);
    }

    /// <summary>Uses an existing bearer token or obtains a server-side client-credentials token.</summary>
    async Task AuthenticateAsync()
    {
        if (!string.IsNullOrEmpty(token))
        {
            return;
        }

        string issuer = ReadOrigin("MDLOGIC_OAUTH_ISSUER", "https://auth.markdownlogic.com");
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(15));
        using var request = new HttpRequestMessage(HttpMethod.Post, issuer + "/oauth/token")
        {
            Content = new FormUrlEncodedContent(new Dictionary<string, string>
            {
                ["grant_type"] = "client_credentials",
                ["client_id"] = Required("MDLOGIC_CLIENT_ID"),
                ["client_secret"] = Required("MDLOGIC_CLIENT_SECRET"),
                ["scope"] = "projects:read documents:read documents:write"
            })
        };
        using var response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, timeout.Token);
        byte[] bytes = await response.Content.ReadAsByteArrayAsync(timeout.Token);
        if (!response.IsSuccessStatusCode)
        {
            throw new ExampleError("Authentication refused. Check the credential grant or reconnect; no replay was attempted.");
        }

        try
        {
            token = JsonNode.Parse(bytes)?["access_token"]?.GetValue<string>();
        }
        catch (JsonException)
        {
            throw new ExampleError("Invalid authorization-server response.");
        }

        if (string.IsNullOrEmpty(token))
        {
            throw new ExampleError("No access token received.");
        }
    }

    /// <summary>Sends an API request and requires a non-null JSON response.</summary>
    public async Task<JsonNode> JsonAsync(string method, string path, object? body = null)
    {
        byte[] bytes = await BytesAsync(method, path, body);
        try
        {
            return JsonNode.Parse(bytes) ?? throw new ExampleError("Invalid API JSON response.");
        }
        catch (JsonException)
        {
            throw new ExampleError("Invalid API JSON response.");
        }
    }

    /// <summary>Reads the complete response under a 15-second deadline for each attempt.</summary>
    /// <remarks>
    /// A lost response does not prove that a write failed. Pending create markers therefore
    /// remain in place on every exception; callers reconcile before trying again.
    /// </remarks>
    public async Task<byte[]> BytesAsync(string method, string path, object? body = null)
    {
        await AuthenticateAsync();
        for (int attempt = 0; attempt < 3; attempt++)
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(15));
            using var request = new HttpRequestMessage(new HttpMethod(method), origin + path);
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token!);
            if (body is not null)
            {
                request.Content = new StringContent(JsonSerializer.Serialize(body), Encoding.UTF8, "application/json");
            }

            HttpResponseMessage response;
            try
            {
                response = await http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, timeout.Token);
            }
            catch (HttpRequestException)
            {
                throw new ExampleError("Network failure. A write may have committed; reconcile the saved mapping and source before any retry.");
            }
            catch (OperationCanceledException)
            {
                throw new ExampleError("Request timed out. Keep the input; reconcile an uncertain write before another attempt.");
            }

            using (response)
            {
                byte[] bytes;
                try
                {
                    bytes = await response.Content.ReadAsByteArrayAsync(timeout.Token);
                }
                catch (OperationCanceledException)
                {
                    throw new ExampleError("Response timed out. Keep the input and reconcile any uncertain write.");
                }

                if (response.IsSuccessStatusCode)
                {
                    return bytes;
                }

                if (response.StatusCode == HttpStatusCode.TooManyRequests && method == "GET" && attempt < 2)
                {
                    await Task.Delay(RetryDelay(response, attempt));
                    continue;
                }

                string? requestId = response.Headers.TryGetValues("x-request-id", out var ids)
                    ? ids.FirstOrDefault()
                    : null;
                throw Failure((int)response.StatusCode, bytes, requestId);
            }
        }

        throw new ExampleError("Read retry budget exhausted.");
    }

    /// <summary>Honors Retry-After without shortening a server-requested wait.</summary>
    static TimeSpan RetryDelay(HttpResponseMessage response, int attempt)
    {
        double seconds = 1 << attempt;
        if (response.Headers.TryGetValues("Retry-After", out var values))
        {
            string value = values.First();
            if (long.TryParse(value, NumberStyles.None, CultureInfo.InvariantCulture, out long integer))
            {
                seconds = integer;
            }
            else if (DateTimeOffset.TryParseExact(value, "r", CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out var date))
            {
                seconds = Math.Max(0, (date - DateTimeOffset.UtcNow).TotalSeconds);
            }
            else
            {
                throw new ExampleError("Invalid Retry-After. Pause and review before another read.");
            }
        }

        // Positive jitter avoids synchronized clients while respecting the server's minimum.
        double jitter = 0.025 + Random.Shared.NextDouble() * 0.025;
        if (seconds + jitter > 5)
        {
            throw new ExampleError("Retry-After exceeds this example's five-second budget with jitter. Pause and retry deliberately later.");
        }

        return TimeSpan.FromSeconds(seconds + jitter);
    }

    /// <summary>Builds useful support guidance without logging arbitrary response text.</summary>
    static ExampleError Failure(int status, byte[] bytes, string? requestId)
    {
        string code = "API_ERROR";
        string reason = "";
        requestId = SafeCode(requestId);
        try
        {
            var error = JsonNode.Parse(bytes);
            code = SafeCode(error?["code"]?.GetValue<string>()) ?? code;
            reason = SafeCode(error?["details"]?["reason"]?.GetValue<string>()) ?? "";
            requestId ??= SafeCode(error?["requestId"]?.GetValue<string>());
        }
        catch (Exception error) when (error is JsonException or InvalidOperationException)
        {
            // A malformed error body must not replace the safe status-based guidance.
        }

        string guidance = status switch
        {
            401 => "Reconnect or correct revoked authorization; no refresh or replay was attempted.",
            409 => "Review the current document and merge changes. Do not remove or silently refresh the revision guard.",
            423 => "Content is temporarily read-only. Input is preserved. Wait for conversion, then review current state before deliberately retrying.",
            429 => "Rate limited. Write requests are single-attempt; pause and review before another attempt.",
            >= 300 and < 400 => "Redirect refused. Configure the canonical origin directly.",
            _ => "Keep the input and mapping; review the failure before another attempt."
        };
        string reasonSuffix = reason.Length == 0 ? "" : " " + reason;
        string requestSuffix = requestId is null ? "" : " requestId=" + requestId;
        return new ExampleError($"HTTP {status} {code}{reasonSuffix}{requestSuffix}. {guidance}");
    }

    static string? SafeCode(string? value)
    {
        // Restrict both length and characters before placing any server field in a log.
        return value is { Length: > 0 and <= 100 }
            && value.All(c => char.IsAsciiLetterOrDigit(c) || c is '_' or '-' or '.')
            ? value
            : null;
    }

    public void Dispose()
    {
        http.Dispose();
    }
}
