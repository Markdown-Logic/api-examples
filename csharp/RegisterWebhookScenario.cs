using System.Text.Json.Nodes;

/// <summary>
/// Registers a destination for the report lifecycle using a separate admin credential.
/// </summary>
static class RegisterWebhookScenario
{
    public static async Task RunAsync(ExampleState context, MdlApi api)
    {
        const string scenario = "06";

        string output = Path.Combine(context.Directory, "webhook.json");
        if (File.Exists(output))
        {
            throw new ExampleError("Webhook already saved. Review the existing destination first.");
        }

        string url = MdlApi.Required("MDLOGIC_WEBHOOK_URL");
        if (!Uri.TryCreate(url, UriKind.Absolute, out var destination) || destination.Scheme != "https" || destination.UserInfo.Length != 0)
        {
            throw new ExampleError("MDLOGIC_WEBHOOK_URL must be a public HTTPS callback URL.");
        }

        string[] events =
        [
            "document.created",
            "document.updated",
            "project.created",
            "project.updated",
            "share.created"
        ];
        var catalogue = await api.JsonAsync("GET", "/api/v1/webhooks/events");
        if (catalogue["events"] is not JsonArray publishedEvents)
        {
            throw new ExampleError("Malformed event catalogue; no destination was created.");
        }

        var available = publishedEvents.Select(ExampleState.RequiredText).ToHashSet();
        if (events.Any(name => !available.Contains(name)))
        {
            throw new ExampleError("Requested webhook events are not available.");
        }

        string path = "/api/v1/teams/" + Uri.EscapeDataString(MdlApi.Required("MDLOGIC_TEAM")) + "/webhooks";
        var body = new { url, events, description = "Generated report lifecycle" };

        string pending = context.BeginCreate("06", path, body);

        var result = await api.JsonAsync("POST", path, body);
        PrivateFiles.WriteJson(output, result); // Secret is returned only once.
        string id = result["webhook"]?["id"]?.GetValue<string>() ?? "";
        string secret = result["secret"]?.GetValue<string>() ?? "";
        if (id.Length == 0 || secret.Length == 0)
        {
            throw new ExampleError("Unusable webhook response retained privately; reconcile pending operation.");
        }

        File.Delete(pending);

        ExampleState.WriteSummary(new { scenario, webhookId = id, file = output });
    }
}
