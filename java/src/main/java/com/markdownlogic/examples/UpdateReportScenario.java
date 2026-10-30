package com.markdownlogic.examples;

import com.google.gson.JsonObject;

/** Scenario 03: carry the exact revision from a read into a guarded replacement. */
final class UpdateReportScenario {
    private UpdateReportScenario() {
    }

    static void run(ApiClient api, ReportState state) throws Exception {
        String content = ReportState.readInput("fixtures/report-updated.md");
        String path = state.documentPath();
        JsonObject current = JsonSupport.requiredObject(api.json("GET", path, null), "document");

        // This task deliberately replaces the synthetic report. A real application
        // compares current.content with its generated text and applies its edit policy here.
        JsonObject payload = JsonSupport.object("content", content,
                "expectedRevision", JsonSupport.requiredText(current, "revision"),
                "changeNote", "Refresh generated report");
        JsonObject result = api.json("PUT", path, payload);
        JsonObject updated = JsonSupport.requiredObject(result, "document");
        state.put("revision", JsonSupport.requiredText(updated, "revision"));
        state.save();

        JsonSupport.print(JsonSupport.object("scenario", "03",
                "documentId", JsonSupport.requiredText(updated, "id"),
                "decision", JsonSupport.requiredText(result, "decision")));
    }
}
