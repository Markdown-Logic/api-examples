using System.Text.Json.Nodes;

/// <summary>
/// Reads one bounded history page and explicitly exports the current report.
/// </summary>
static class ExportReportScenario
{
    public static async Task RunAsync(ExampleState context, MdlApi api)
    {
        const string scenario = "04";

        var page = await api.JsonAsync("GET", context.DocumentPath() + "/versions?limit=20&offset=0");
        if (page["items"] is not JsonArray items
            || page["hasMore"] is not JsonValue hasMoreNode
            || !hasMoreNode.TryGetValue<bool>(out bool hasMore))
        {
            throw new ExampleError("Malformed history page; export stopped.");
        }
        if (items.Count > 0)
        {
            if (items[0] is not JsonObject version)
            {
                throw new ExampleError("Malformed history entry; export stopped.");
            }

            string versionId = ExampleState.RequiredText(version["id"]);
            await api.JsonAsync("GET", context.DocumentPath() + "/versions/" + Uri.EscapeDataString(versionId));
        }

        byte[] rendered = await api.BytesAsync("GET", context.DocumentPath() + "/renders/html");
        string output = Path.Combine(context.Directory, "report.html");
        PrivateFiles.Write(output, rendered);

        ExampleState.WriteSummary(new { scenario, versions = items.Count, hasMore, file = output });
    }
}
