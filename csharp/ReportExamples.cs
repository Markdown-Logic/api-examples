/// <summary>Routes each numbered command to one task-focused example.</summary>
static class ReportExamples
{
    public static async Task RunAsync(string scenario)
    {
        if (!new[] { "01", "02", "03", "04", "05", "06" }.Contains(scenario))
        {
            throw new ExampleError("Choose 01, 02, 03, 04, 05 or 06.");
        }

        var state = new ExampleState();
        using var api = new MdlApi();

        Task operation = scenario switch
        {
            "01" => CreateProjectScenario.RunAsync(state, api),
            "02" => StoreReportScenario.RunAsync(state, api),
            "03" => UpdateReportScenario.RunAsync(state, api),
            "04" => ExportReportScenario.RunAsync(state, api),
            "05" => ShareReportScenario.RunAsync(state, api),
            "06" => RegisterWebhookScenario.RunAsync(state, api),
            _ => throw new ExampleError("Unknown scenario.")
        };
        await operation;
    }
}
