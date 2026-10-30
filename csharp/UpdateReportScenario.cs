/// <summary>
/// Reads the current revision before replacing the approved report source.
/// </summary>
static class UpdateReportScenario
{
    public static async Task RunAsync(ExampleState context, MdlApi api)
    {
        const string scenario = "03";

        string content = ExampleState.ReadInput("fixtures/report-updated.md");
        var read = await api.JsonAsync("GET", context.DocumentPath());
        string revision = ExampleState.RequiredText(read["document"]?["revision"]);

        // The synthetic report is approved input. A real app must review/merge a
        // user's intervening changes before replacing the complete source.
        var result = await api.JsonAsync("PUT", context.DocumentPath(), new
        {
            content,
            expectedRevision = revision,
            changeNote = "Refresh generated report"
        });
        context.Mapping["revision"] = ExampleState.RequiredText(result["document"]?["revision"]);
        context.Save();

        ExampleState.WriteSummary(new { scenario, documentId = context.Mapped("documentId") });
    }
}
