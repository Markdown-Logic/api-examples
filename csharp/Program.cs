using System.Text.Json.Nodes;

try
{
    if (args.Length != 1)
        throw new ExampleError("Choose 01, 02, 03, 04, 05, 06 or webhook.");
    if (args[0] == "webhook")
        await WebhookReceiver.Run();
    else
        await new ReportExamples().Run(args[0]);
}
catch (ExampleError error)
{
    Console.Error.WriteLine(error.Message);
    Environment.ExitCode = 1;
}
catch (Exception)
{
    // Never echo raw server responses, credentials, document text or platform paths.
    Console.Error.WriteLine("Operation failed. Keep the input and local mapping; reconcile any uncertain write before another attempt.");
    Environment.ExitCode = 1;
}

sealed class ReportExamples
{
    readonly string directory = PrivateFiles.StateDirectory();
    readonly JsonObject state;

    public ReportExamples()
    {
        string path = Path.Combine(directory, "state.json");
        state = File.Exists(path)
            ? JsonNode.Parse(File.ReadAllText(path))?.AsObject() ?? throw new ExampleError("Invalid local state.")
            : new JsonObject();
    }

    string Mapped(string key) => state[key]?.GetValue<string>() is { Length: > 0 } value
        ? value : throw new ExampleError("Complete the earlier scenarios first.");
    static string RequiredText(JsonNode? node) => node?.GetValue<string>() is { Length: > 0 } value
        ? value : throw new ExampleError("Required response field is missing or empty. Keep pending state and reconcile.");
    void Save() => PrivateFiles.WriteJson(Path.Combine(directory, "state.json"), state);
    string BeginCreate(string scenario, string path, object body)
    {
        string pending = Path.Combine(directory, "pending-" + scenario + ".json");
        if (File.Exists(pending)) throw new ExampleError("A prior create is pending. Reconcile it with MDL before removing the marker or creating again.");
        // Keep the original target and payload even if environment/input changes
        // before recovery. This private file contains generated report source.
        string apiOrigin = new Uri(Environment.GetEnvironmentVariable("MDLOGIC_API_ORIGIN") ?? "https://api.markdownlogic.com").GetLeftPart(UriPartial.Authority);
        PrivateFiles.WriteNew(pending, System.Text.Json.JsonSerializer.SerializeToUtf8Bytes(new { scenario, status = "pending", apiOrigin, method = "POST", path, body }));
        return pending;
    }
    static void Show(object value) => Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(value));
    string ProjectPath() => "/api/v1/projects/" + Uri.EscapeDataString(Mapped("projectId"));
    string DocumentPath() => ProjectPath() + "/documents/" + Uri.EscapeDataString(Mapped("documentId"));
    static string Input(string fallback) => new System.Text.UTF8Encoding(false, true).GetString(File.ReadAllBytes(Environment.GetEnvironmentVariable("MDLOGIC_INPUT") ?? fallback));

    public async Task Run(string scenario)
    {
        if (!new[] { "01", "02", "03", "04", "05", "06" }.Contains(scenario))
            throw new ExampleError("Choose 01, 02, 03, 04, 05 or 06.");
        using var api = new MdlApi();
        switch (scenario)
        {
            case "01":
            {
                if (state["projectId"] is not null)
                    throw new ExampleError("Project already mapped. Keep its mapping; do not create a duplicate.");
                string team = Uri.EscapeDataString(MdlApi.Required("MDLOGIC_TEAM"));
                string path = $"/api/v1/teams/{team}/projects";
                var body = new { name = "Report integration example", mode = "document" };
                string pending = BeginCreate("01", path, body);
                var created = await api.Json("POST", path, body);
                state["projectId"] = RequiredText(created["project"]?["id"]);
                Save(); // Persist before any later call can fail.
                File.Delete(pending);
                var page = await api.Json("GET", $"/api/v1/teams/{team}/projects?limit=50&offset=0");
                await api.Json("PATCH", ProjectPath(), new { name = "Report integration example" });
                Show(new { scenario, projectId = Mapped("projectId"), listed = page["items"]!.AsArray().Count });
                break;
            }
            case "02":
            {
                if (state["documentId"] is not null)
                    throw new ExampleError("Report already mapped. Use scenario 03 to update it.");
                string content = Input("fixtures/report.md");
                string project = ProjectPath(); // Validate mapping before making a marker.
                string path = project + "/artifacts";
                var body = new { name = "report.md", content, format = "markdown", ifNotExists = true };
                string pending = BeginCreate("02", path, body);
                var result = await api.Json("POST", path, body);
                state["documentId"] = RequiredText(result["artifact"]?["id"]);
                state["revision"] = RequiredText(result["artifact"]?["revision"]);
                Save();
                File.Delete(pending);
                Show(new { scenario, documentId = Mapped("documentId") });
                break;
            }
            case "03":
            {
                string content = Input("fixtures/report-updated.md");
                var read = await api.Json("GET", DocumentPath());
                string revision = RequiredText(read["document"]?["revision"]);
                // The synthetic report is approved input. A real app must review/merge a
                // user's intervening changes before replacing the complete source.
                var result = await api.Json("PUT", DocumentPath(), new
                {
                    content, expectedRevision = revision, changeNote = "Refresh generated report"
                });
                state["revision"] = RequiredText(result["document"]?["revision"]);
                Save();
                Show(new { scenario, documentId = Mapped("documentId") });
                break;
            }
            case "04":
            {
                var page = await api.Json("GET", DocumentPath() + "/versions?limit=20&offset=0");
                var items = page["items"]?.AsArray() ?? throw new ExampleError("Malformed history page; export stopped.");
                bool hasMore = page["hasMore"]?.GetValue<bool>() ?? throw new ExampleError("Malformed history page; export stopped.");
                if (items.Count > 0)
                    await api.Json("GET", DocumentPath() + "/versions/" + Uri.EscapeDataString(items[0]!["id"]!.GetValue<string>()));
                byte[] rendered = await api.Bytes("GET", DocumentPath() + "/renders/html");
                string output = Path.Combine(directory, "report.html");
                PrivateFiles.Write(output, rendered);
                Show(new { scenario, versions = items.Count, hasMore, file = output });
                break;
            }
            case "05":
            {
                // Invoking this command is the explicit request to create a public link.
                string output = Path.Combine(directory, "share.json");
                if (File.Exists(output)) throw new ExampleError("Share already saved. Review it before requesting another link.");
                string path = DocumentPath() + "/shares";
                var body = new { expiresInDays = 30 };
                string pending = BeginCreate("05", path, body);
                var result = await api.Json("POST", path, body);
                PrivateFiles.WriteJson(output, result);
                string id = result["share"]?["id"]?.GetValue<string>() ?? "";
                string url = result["share"]?["url"]?.GetValue<string>() ?? "";
                if (id.Length == 0 || url.Length == 0) throw new ExampleError("Unusable share response retained privately; reconcile pending operation.");
                File.Delete(pending);
                Show(new { scenario, shareId = id, file = output });
                break;
            }
            case "06":
            {
                string output = Path.Combine(directory, "webhook.json");
                if (File.Exists(output)) throw new ExampleError("Webhook already saved. Review the existing destination first.");
                string url = MdlApi.Required("MDLOGIC_WEBHOOK_URL");
                if (!Uri.TryCreate(url, UriKind.Absolute, out var destination) || destination.Scheme != "https" || destination.UserInfo.Length != 0)
                    throw new ExampleError("MDLOGIC_WEBHOOK_URL must be a public HTTPS callback URL.");
                string[] events = ["document.created", "document.updated", "project.created", "project.updated", "share.created"];
                var catalogue = await api.Json("GET", "/api/v1/webhooks/events");
                var available = catalogue["events"]!.AsArray().Select(item => item!.GetValue<string>()).ToHashSet();
                if (events.Any(name => !available.Contains(name))) throw new ExampleError("Requested webhook events are not available.");
                string path = "/api/v1/teams/" + Uri.EscapeDataString(MdlApi.Required("MDLOGIC_TEAM")) + "/webhooks";
                var body = new { url, events, description = "Generated report lifecycle" };
                string pending = BeginCreate("06", path, body);
                var result = await api.Json("POST", path, body);
                PrivateFiles.WriteJson(output, result); // Secret is returned only once.
                string id = result["webhook"]?["id"]?.GetValue<string>() ?? "";
                string secret = result["secret"]?.GetValue<string>() ?? "";
                if (id.Length == 0 || secret.Length == 0) throw new ExampleError("Unusable webhook response retained privately; reconcile pending operation.");
                File.Delete(pending);
                Show(new { scenario, webhookId = id, file = output });
                break;
            }
        }
    }
}
