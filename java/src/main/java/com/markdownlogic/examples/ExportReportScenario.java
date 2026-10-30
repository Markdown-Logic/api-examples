package com.markdownlogic.examples;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

/** Scenario 04: inspect a bounded history page, then explicitly export the live document. */
final class ExportReportScenario {
    private ExportReportScenario() {
    }

    static void run(ApiClient api, ReportState state) throws Exception {
        String path = state.documentPath();
        JsonObject page = api.json("GET", path + "/versions?limit=20&offset=0", null);
        if (!page.has("items") || !page.get("items").isJsonArray()
                || !page.has("hasMore") || !page.get("hasMore").isJsonPrimitive()
                || !page.get("hasMore").getAsJsonPrimitive().isBoolean()) {
            throw new ExampleFailure("Malformed history page; export stopped.");
        }

        JsonArray items = page.getAsJsonArray("items");
        if (!items.isEmpty()) {
            // A snapshot ID selects historical content; it is not a write revision token.
            if (!items.get(0).isJsonObject()) {
                throw new ExampleFailure("Malformed history entry; export stopped.");
            }
            String versionId = JsonSupport.requiredText(items.get(0).getAsJsonObject(), "id");
            api.json("GET", path + "/versions/" + ExampleConfig.encode(versionId), null);
        }
        PrivateFiles.replace(state.file("report.html"), api.exportHtml(path));
        JsonSupport.print(JsonSupport.object("scenario", "04", "versionsListed", items.size(),
                "hasMore", page.get("hasMore").getAsBoolean(),
                "exportFile", state.file("report.html").toString()));
    }
}
