/// <summary>
/// Creates a project, saves its stable ID, then lists and updates its metadata.
/// </summary>
static class CreateProjectScenario
{
    public static async Task RunAsync(ExampleState context, MdlApi api)
    {
        const string scenario = "01";

        if (context.Mapping["projectId"] is not null)
        {
            throw new ExampleError("Project already mapped. Keep its mapping; do not create a duplicate.");
        }

        string team = Uri.EscapeDataString(MdlApi.Required("MDLOGIC_TEAM"));
        string path = $"/api/v1/teams/{team}/projects";
        var body = new { name = "Report integration example", mode = "document" };

        string pending = context.BeginCreate("01", path, body);

        var created = await api.JsonAsync("POST", path, body);
        context.Mapping["projectId"] = ExampleState.RequiredText(created["project"]?["id"]);
        context.Save(); // Persist before any later call can fail.
        File.Delete(pending);

        var page = await api.JsonAsync("GET", $"/api/v1/teams/{team}/projects?limit=50&offset=0");
        await api.JsonAsync("PATCH", context.ProjectPath(), new { name = "Report integration example" });

        ExampleState.WriteSummary(new
        {
            scenario,
            projectId = context.Mapped("projectId"),
            listed = page["items"]!.AsArray().Count
        });
    }
}
