using System.Globalization;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

static class WebhookReceiver
{
    const int MaximumBodyBytes = 1024 * 1024;

    public static async Task Run()
    {
        string secret = MdlApi.Required("MDLOGIC_WEBHOOK_SECRET");
        string portText = Environment.GetEnvironmentVariable("PORT") ?? "8080";
        if (!int.TryParse(portText, out int port) || port is < 1 or > 65535) throw new ExampleError("Invalid PORT.");
        string inbox = Path.Combine(PrivateFiles.StateDirectory(), "inbox");
        PrivateFiles.EnsureDirectory(inbox);
        using var listener = new HttpListener();
        string bind = Environment.GetEnvironmentVariable("MDLOGIC_WEBHOOK_BIND") ?? "127.0.0.1";
        if (bind != "127.0.0.1" && bind != "0.0.0.0") throw new ExampleError("Invalid webhook bind address.");
        listener.Prefixes.Add($"http://{(bind == "0.0.0.0" ? "+" : bind)}:{port}/");
        listener.Start();
        Console.WriteLine(JsonSerializer.Serialize(new { listening = $"http://127.0.0.1:{port}/webhook" }));
        // Sequential acceptance keeps this local teaching example small. A real
        // ingress needs bounded concurrency and a transactional durable queue.
        while (true)
        {
            var context = await listener.GetContextAsync();
            try { await Accept(context, secret, inbox); }
            catch (Exception)
            {
                context.Response.StatusCode = 500;
                context.Response.Close();
            }
        }
    }

    static async Task Accept(HttpListenerContext context, string secret, string inbox)
    {
        var request = context.Request;
        if (request.HttpMethod != "POST" || request.Url?.AbsolutePath != "/webhook")
        {
            Reply(context, 404);
            return;
        }
        if (request.ContentLength64 > MaximumBodyBytes)
        {
            Reply(context, 413);
            return;
        }
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        using var buffer = new MemoryStream();
        byte[] chunk = new byte[8192];
        while (true)
        {
            int count = await request.InputStream.ReadAsync(chunk, timeout.Token);
            if (count == 0) break;
            if (buffer.Length + count > MaximumBodyBytes)
            {
                Reply(context, 413);
                return;
            }
            buffer.Write(chunk, 0, count);
        }
        byte[] body = buffer.ToArray();
        if (!Verify(request.Headers["MDL-Signature"] ?? "", body, secret))
        {
            Reply(context, 401);
            return;
        }
        JsonNode? envelope;
        string id, type;
        try
        {
            envelope = JsonNode.Parse(body);
            id = envelope?["id"]?.GetValue<string>() ?? "";
            type = envelope?["type"]?.GetValue<string>() ?? "";
            if (id.Length == 0 || type.Length == 0 || id != request.Headers["MDL-Event-Id"]
                || (request.Headers["MDL-Event-Type"] is string headerType && type != headerType))
            {
                Reply(context, 400);
                return;
            }
        }
        catch (Exception error) when (error is JsonException or InvalidOperationException)
        {
            Reply(context, 400);
            return;
        }
        // The event id comes from the authenticated body. Never use delivery id:
        // It identifies delivery to one destination and remains stable across retries.
        string name = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(id))).ToLowerInvariant();
        string final = Path.Combine(inbox, name + ".json");
        string temporary = Path.Combine(inbox, "." + Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            PrivateFiles.WriteNew(temporary, body);
            try { File.Move(temporary, final, false); }
            catch (IOException) when (File.Exists(final))
            {
                Reply(context, 200); // Already durably accepted, including after restart.
                return;
            }
            Reply(context, 202);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }

    static bool Verify(string header, byte[] body, string secret)
    {
        string[] fields = header.Split(',').Select(part => part.Trim()).ToArray();
        string? timestampText = fields.FirstOrDefault(part => part.StartsWith("t=", StringComparison.Ordinal))?[2..];
        long now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        if (!long.TryParse(timestampText, NumberStyles.None, CultureInfo.InvariantCulture, out long timestamp) || timestamp <= 0
            || timestamp < now - 300 || timestamp > now + 300) return false;
        byte[] prefix = Encoding.ASCII.GetBytes(timestamp.ToString(CultureInfo.InvariantCulture) + ".");
        byte[] material = new byte[prefix.Length + body.Length];
        prefix.CopyTo(material, 0);
        body.CopyTo(material, prefix.Length);
        byte[] expected = HMACSHA256.HashData(Encoding.UTF8.GetBytes(secret), material);
        foreach (string field in fields.Where(part => part.StartsWith("v1=", StringComparison.Ordinal)))
        {
            string digest = field[3..];
            if (digest.Length != 64 || digest.Any(c => !Uri.IsHexDigit(c))) continue;
            byte[] supplied = Convert.FromHexString(digest);
            if (CryptographicOperations.FixedTimeEquals(expected, supplied)) return true;
        }
        return false;
    }

    static void Reply(HttpListenerContext context, int status)
    {
        context.Response.StatusCode = status;
        context.Response.ContentLength64 = 0;
        context.Response.Close();
    }
}
