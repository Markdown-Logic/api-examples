/// <summary>
/// Stores generated Markdown once and remembers its document ID and revision.
/// </summary>
static class StoreReportScenario
{
    public static async Task RunAsync(ExampleState context, MdlApi api)
    {
        const string scenario = "02";

        if (context.Mapping["documentId"] is not null)
        {
            throw new ExampleError("Report already mapped. Use scenario 03 to update it.");
        }

        string content = ExampleState.ReadInput("fixtures/report.md");
        string project = context.ProjectPath(); // Validate mapping before making a marker.
        string path = project + "/artifacts";
        var body = new { name = "report.md", content, format = "markdown", ifNotExists = true };

        string pending = context.BeginCreate("02", path, body);

        var result = await api.JsonAsync("POST", path, body);
        context.Mapping["documentId"] = ExampleState.RequiredText(result["artifact"]?["id"]);
        context.Mapping["revision"] = ExampleState.RequiredText(result["artifact"]?["revision"]);
        context.Save();
        File.Delete(pending);

        ExampleState.WriteSummary(new { scenario, documentId = context.Mapped("documentId") });
    }
}
