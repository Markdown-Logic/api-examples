using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

/// <summary>
/// Keeps stable resource mappings and unfinished create requests in private local files.
/// </summary>
/// <remarks>Use one state directory per integration and do not share it among writers.</remarks>
sealed class ExampleState
{
    public string Directory { get; } = PrivateFiles.StateDirectory();
    public JsonObject Mapping { get; }

    public ExampleState()
    {
        string path = Path.Combine(Directory, "state.json");
        if (!File.Exists(path))
        {
            Mapping = new JsonObject();
            return;
        }

        try
        {
            Mapping = JsonNode.Parse(File.ReadAllText(path)) as JsonObject
                ?? throw new ExampleError("Local state must be a JSON object. Review state.json before continuing.");
        }
        catch (JsonException)
        {
            throw new ExampleError("Local state is invalid JSON. Review state.json before continuing.");
        }
    }

    /// <summary>Requires a stable mapping from an earlier scenario.</summary>
    public string Mapped(string key)
    {
        if (Mapping[key] is JsonValue node
            && node.TryGetValue<string>(out string? value)
            && !string.IsNullOrEmpty(value))
        {
            return value;
        }

        throw new ExampleError("Complete the earlier scenarios first; the saved " + key + " must be a nonempty string.");
    }

    /// <summary>Rejects missing response values before they can replace saved mappings.</summary>
    public static string RequiredText(JsonNode? node)
    {
        if (node is JsonValue valueNode
            && valueNode.TryGetValue<string>(out string? value)
            && !string.IsNullOrEmpty(value))
        {
            return value;
        }

        throw new ExampleError("Required response field must be a nonempty string. Keep pending state and reconcile.");
    }

    public void Save()
    {
        PrivateFiles.WriteJson(Path.Combine(Directory, "state.json"), Mapping);
    }

    /// <summary>
    /// Records the exact create intent before sending it; an existing marker blocks repeats.
    /// </summary>
    /// <remarks>
    /// This marker is application-side duplicate prevention, not an API idempotency key.
    /// After a timeout, inspect the original target and reconcile server state before clearing it.
    /// </remarks>
    public string BeginCreate(string scenario, string path, object body)
    {
        string pending = Path.Combine(Directory, "pending-" + scenario + ".json");
        if (File.Exists(pending))
        {
            throw new ExampleError("A prior create is pending. Reconcile it with MDL before removing the marker or creating again.");
        }

        // Preserve the original target and payload if configuration changes during recovery.
        string configuredOrigin = Environment.GetEnvironmentVariable("MDLOGIC_API_ORIGIN")
            ?? "https://api.markdownlogic.com";
        string apiOrigin = new Uri(configuredOrigin).GetLeftPart(UriPartial.Authority);
        byte[] intent = JsonSerializer.SerializeToUtf8Bytes(new
        {
            scenario,
            status = "pending",
            apiOrigin,
            method = "POST",
            path,
            body
        });
        PrivateFiles.WriteNew(pending, intent);
        return pending;
    }

    public string ProjectPath()
    {
        return "/api/v1/projects/" + Uri.EscapeDataString(Mapped("projectId"));
    }

    public string DocumentPath()
    {
        return ProjectPath() + "/documents/" + Uri.EscapeDataString(Mapped("documentId"));
    }

    /// <summary>Reads strict UTF-8 without changing line endings or editing the input.</summary>
    public static string ReadInput(string fallback)
    {
        string path = Environment.GetEnvironmentVariable("MDLOGIC_INPUT") ?? fallback;
        return new UTF8Encoding(false, true).GetString(File.ReadAllBytes(path));
    }

    public static void WriteSummary(object value)
    {
        Console.WriteLine(JsonSerializer.Serialize(value));
    }
}
