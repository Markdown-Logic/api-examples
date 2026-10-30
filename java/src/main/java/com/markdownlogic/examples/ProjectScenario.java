package com.markdownlogic.examples;

import com.google.gson.JsonObject;

/** Scenario 01: provision a project once, list one page, and update its name. */
final class ProjectScenario {
    private ProjectScenario() {
    }

    static void run(ApiClient api, ReportState state) throws Exception {
        if (state.has("projectId")) {
            throw new ExampleFailure("A project is already mapped. Reuse it; do not create another blindly.");
        }

        String team = ExampleConfig.encode(ExampleConfig.required("MDLOGIC_TEAM"));
        String path = "/api/v1/teams/" + team + "/projects";
        JsonObject payload = JsonSupport.object("name", "Report integration example", "mode", "document");
        state.beginCreate("01", api.origin(), path, payload);
        JsonObject created = api.json("POST", path, payload);
        String id = JsonSupport.requiredText(JsonSupport.requiredObject(created, "project"), "id");

        // Save the new stable ID before a later read or metadata update can fail.
        state.put("projectId", id);
        state.save();
        state.completeCreate("01");

        JsonObject page = api.json("GET", path + "?limit=50&offset=0", null);
        api.json("PATCH", state.projectPath(), JsonSupport.object("name", "Report integration example"));
        JsonSupport.print(JsonSupport.object("scenario", "01", "projectId", id,
                "listed", page.getAsJsonArray("items").size()));
    }
}
