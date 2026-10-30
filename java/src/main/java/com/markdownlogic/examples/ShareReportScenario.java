package com.markdownlogic.examples;

import com.google.gson.JsonObject;
import java.nio.file.Files;

/** Scenario 05: create a time-limited share only when explicitly requested. */
final class ShareReportScenario {
    private ShareReportScenario() {
    }

    static void run(ApiClient api, ReportState state) throws Exception {
        if (Files.exists(state.file("share.json"))) {
            throw new ExampleFailure("A share is already saved. Review it before creating another.");
        }

        String path = state.documentPath() + "/shares";
        JsonObject payload = JsonSupport.object("expiresInDays", 30);
        state.beginCreate("05", api.origin(), path, payload);
        JsonObject result = api.json("POST", path, payload);

        // Keep the full response privately even if validation fails, for reconciliation.
        PrivateFiles.replace(state.file("share.json"), JsonSupport.bytes(result));
        String id = JsonSupport.requiredText(JsonSupport.requiredObject(result, "share"), "id");
        JsonSupport.requiredText(JsonSupport.requiredObject(result, "share"), "url");
        state.completeCreate("05");
        JsonSupport.print(JsonSupport.object("scenario", "05", "shareId", id,
                "shareFile", state.file("share.json").toString()));
    }
}
