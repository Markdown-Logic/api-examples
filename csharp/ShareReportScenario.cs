/// <summary>
/// Creates a share link only when this scenario is explicitly requested.
/// </summary>
static class ShareReportScenario
{
    public static async Task RunAsync(ExampleState context, MdlApi api)
    {
        const string scenario = "05";

        // Invoking this command is the explicit request to create a public link.
        string output = Path.Combine(context.Directory, "share.json");
        if (File.Exists(output))
        {
            throw new ExampleError("Share already saved. Review it before requesting another link.");
        }

        string path = context.DocumentPath() + "/shares";
        var body = new { expiresInDays = 30 };

        string pending = context.BeginCreate("05", path, body);

        var result = await api.JsonAsync("POST", path, body);
        PrivateFiles.WriteJson(output, result);
        string id = result["share"]?["id"]?.GetValue<string>() ?? "";
        string url = result["share"]?["url"]?.GetValue<string>() ?? "";
        if (id.Length == 0 || url.Length == 0)
        {
            throw new ExampleError("Unusable share response retained privately; reconcile pending operation.");
        }

        File.Delete(pending);

        ExampleState.WriteSummary(new { scenario, shareId = id, file = output });
    }
}
