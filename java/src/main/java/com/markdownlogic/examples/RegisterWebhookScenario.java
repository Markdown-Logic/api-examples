package com.markdownlogic.examples;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;
import java.net.URI;
import java.nio.file.Files;
import java.util.List;

/** Scenario 06: register a report subscription using a separate owner/admin grant. */
final class RegisterWebhookScenario {
    private static final List<String> EVENTS = List.of("document.created", "document.updated",
            "project.created", "project.updated", "share.created");

    private RegisterWebhookScenario() {
    }

    static void run(ApiClient api, ReportState state) throws Exception {
        if (Files.exists(state.file("webhook.json"))) {
            throw new ExampleFailure("A webhook response is already saved. Reuse or rotate it rather than registering again.");
        }

        String team = ExampleConfig.encode(ExampleConfig.required("MDLOGIC_TEAM"));
        String callback = ExampleConfig.required("MDLOGIC_WEBHOOK_URL");
        URI uri = URI.create(callback);
        if (!"https".equals(uri.getScheme()) || uri.getHost() == null
                || uri.getUserInfo() != null || uri.getFragment() != null) {
            throw new ExampleFailure("MDLOGIC_WEBHOOK_URL must be an HTTPS receiver URL without userinfo or fragment.");
        }

        JsonObject response = api.json("GET", "/api/v1/webhooks/events", null);
        if (!response.has("events") || !response.get("events").isJsonArray()) {
            throw new ExampleFailure("Malformed event catalogue; no destination was registered.");
        }
        JsonArray catalogue = response.getAsJsonArray("events");
        JsonArray subscriptions = new JsonArray();
        for (String event : EVENTS) {
            if (!catalogue.contains(new JsonPrimitive(event))) {
                throw new ExampleFailure("The server event catalogue does not support the example subscription.");
            }
            subscriptions.add(event);
        }
        JsonObject payload = JsonSupport.object("url", callback, "description", "Generated report lifecycle");
        payload.add("events", subscriptions);
        String path = "/api/v1/teams/" + team + "/webhooks";
        state.beginCreate("06", api.origin(), path, payload);
        JsonObject result = api.json("POST", path, payload);

        // The signing secret is shown once. Save it privately before inspecting the response.
        PrivateFiles.replace(state.file("webhook.json"), JsonSupport.bytes(result));
        String id = JsonSupport.requiredText(JsonSupport.requiredObject(result, "webhook"), "id");
        JsonSupport.requiredText(result, "secret");
        state.completeCreate("06");
        JsonSupport.print(JsonSupport.object("scenario", "06", "webhookId", id,
                "secretFile", state.file("webhook.json").toString()));
    }
}
