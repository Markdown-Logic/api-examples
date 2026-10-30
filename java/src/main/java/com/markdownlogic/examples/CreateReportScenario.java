package com.markdownlogic.examples;

import com.google.gson.JsonObject;

/** Scenario 02: store generated Markdown without replacing an existing named report. */
final class CreateReportScenario {
    private CreateReportScenario() {
    }

    static void run(ApiClient api, ReportState state) throws Exception {
        if (state.has("documentId")) {
            throw new ExampleFailure("A report is already mapped. Use scenario 03 to update it.");
        }

        String content = ReportState.readInput("fixtures/report.md");
        String path = state.projectPath() + "/artifacts";
        // A stable name plus ifNotExists protects against accidental replacement.
        JsonObject payload = JsonSupport.object("name", "report.md", "content", content,
                "format", "markdown", "ifNotExists", true);
        state.beginCreate("02", api.origin(), path, payload);
        JsonObject result = api.json("POST", path, payload);
        JsonObject document = JsonSupport.requiredObject(result, "artifact");
        String id = JsonSupport.requiredText(document, "id");
        String revision = JsonSupport.requiredText(document, "revision");

        state.put("documentId", id);
        state.put("revision", revision);
        state.save();
        state.completeCreate("02");
        JsonSupport.print(JsonSupport.object("scenario", "02", "documentId", id,
                "decision", JsonSupport.requiredText(result, "decision")));
    }
}
