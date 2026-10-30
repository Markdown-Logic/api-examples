package com.markdownlogic.examples;

import com.google.gson.JsonObject;
import java.math.BigInteger;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/** HTTP/authentication helpers for the examples, with intentionally conservative retries. */
final class ApiClient {
    private static final int MAX_ATTEMPTS = 3;
    private static final long MAX_WAIT_MILLIS = 5_000;
    private final HttpClient http = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(15))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();
    private final URI origin;
    private final String token;

    ApiClient() throws Exception {
        origin = ExampleConfig.checkedOrigin(ExampleConfig.environment(
                "MDLOGIC_API_ORIGIN", "https://api.markdownlogic.com"));
        token = accessToken();
    }

    URI origin() {
        return origin;
    }

    /**
     * Send a JSON request to one API path and require an object response.
     * Callers validate the fields they need before saving mappings or clearing journals.
     */
    JsonObject json(String method, String path, JsonObject body) throws Exception {
        byte[] payload = body == null ? null : JsonSupport.bytes(body);
        HttpResponse<byte[]> response = request(method, origin.resolve(path), payload,
                "application/json", true);
        return JsonSupport.parseObject(response.body());
    }

    /** Return render bytes unchanged; exported content never enters routine console output. */
    byte[] exportHtml(String documentPath) throws Exception {
        return request("GET", origin.resolve(documentPath + "/renders/html"), null,
                "application/json", true).body();
    }

    /** Own-account automation only; user-delegated authorization is explained in the guide. */
    private String accessToken() throws Exception {
        String supplied = System.getenv("MDLOGIC_TOKEN");
        if (supplied != null && !supplied.isBlank()) {
            return supplied;
        }

        URI issuer = ExampleConfig.checkedOrigin(ExampleConfig.environment(
                "MDLOGIC_OAUTH_ISSUER", "https://auth.markdownlogic.com"));
        String form = "grant_type=client_credentials&client_id="
                + ExampleConfig.encode(ExampleConfig.required("MDLOGIC_CLIENT_ID"))
                + "&client_secret=" + ExampleConfig.encode(ExampleConfig.required("MDLOGIC_CLIENT_SECRET"))
                + "&scope=" + ExampleConfig.encode("projects:read documents:read documents:write");
        HttpResponse<byte[]> response = request("POST", issuer.resolve("/oauth/token"),
                form.getBytes(StandardCharsets.UTF_8), "application/x-www-form-urlencoded", false);
        return JsonSupport.requiredText(JsonSupport.parseObject(response.body()), "access_token");
    }

    /**
     * Retry only explicit GET rate limits. A lost mutation response cannot tell us whether
     * the server committed the change, so callers must reconcile it rather than resend it.
     */
    private HttpResponse<byte[]> request(String method, URI uri, byte[] body,
            String contentType, boolean authenticated) throws Exception {
        for (int attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
            HttpRequest.Builder builder = HttpRequest.newBuilder(uri)
                    .timeout(Duration.ofSeconds(15))
                    .header("Accept", "application/json");
            if (authenticated) {
                builder.header("Authorization", "Bearer " + token);
            }
            if (body != null) {
                builder.header("Content-Type", contentType);
            }
            builder.method(method, body == null ? HttpRequest.BodyPublishers.noBody()
                    : HttpRequest.BodyPublishers.ofByteArray(body));

            CompletableFuture<HttpResponse<byte[]>> future = http.sendAsync(
                    builder.build(), HttpResponse.BodyHandlers.ofByteArray());
            HttpResponse<byte[]> response;
            try {
                // Bound the complete body, not just receipt of the response headers.
                response = future.get(15, TimeUnit.SECONDS);
            } catch (InterruptedException exception) {
                future.cancel(true);
                Thread.currentThread().interrupt();
                throw new ExampleFailure("Request interrupted. Keep input and reconcile an uncertain write before another attempt.");
            } catch (ExecutionException | TimeoutException exception) {
                future.cancel(true);
                throw new ExampleFailure(method.equals("GET")
                        ? "Read failed or timed out. No automatic network retry."
                        : "Write outcome is uncertain. Keep input; reconcile current server state before another write.");
            }

            int status = response.statusCode();
            if (status == 429 && method.equals("GET") && attempt < MAX_ATTEMPTS - 1) {
                waitBeforeReadRetry(response, attempt);
                continue;
            }
            if (status < 200 || status >= 300) {
                throw apiFailure(response);
            }
            return response;
        }
        throw new AssertionError("Retry loop must return or fail.");
    }

    private static void waitBeforeReadRetry(HttpResponse<byte[]> response, int attempt) {
        long delay = retryDelay(response.headers().firstValue("Retry-After").orElse(null), attempt);
        if (delay > MAX_WAIT_MILLIS) {
            throw new ExampleFailure("HTTP 429: server wait exceeds this example's five-second retry budget. Retry later.");
        }
        if (delay < MAX_WAIT_MILLIS) {
            // Keep jitter inside the wait budget without shortening the server's requested wait.
            delay += ThreadLocalRandom.current().nextLong(1, Math.min(100, MAX_WAIT_MILLIS - delay) + 1);
        }
        try {
            Thread.sleep(delay);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new ExampleFailure("Read retry interrupted; no further request was sent.");
        }
    }

    private static long retryDelay(String value, int attempt) {
        if (value != null) {
            try {
                if (value.matches("[0-9]+")) {
                    // Compare before narrowing: an enormous header must not overflow into a short wait.
                    BigInteger seconds = new BigInteger(value);
                    return seconds.compareTo(BigInteger.valueOf(5)) > 0
                            ? MAX_WAIT_MILLIS + 1 : seconds.longValue() * 1_000;
                }
                Instant retryAt = ZonedDateTime.parse(value, DateTimeFormatter.RFC_1123_DATE_TIME).toInstant();
                return Math.max(0, Duration.between(Instant.now(), retryAt).toMillis());
            } catch (RuntimeException ignored) {
                // Invalid Retry-After uses the bounded exponential fallback below.
            }
        }
        return (1L << attempt) * 1_000;
    }

    /** Include useful diagnostics, but never raw bodies, token values or response messages. */
    private static ExampleFailure apiFailure(HttpResponse<byte[]> response) {
        String code = "";
        String reason = "";
        try {
            JsonObject error = JsonSupport.parseObject(response.body());
            if (isString(error, "code")) {
                String candidate = error.get("code").getAsString();
                if (candidate.matches("[A-Z][A-Z0-9_]{0,63}")) {
                    code = " " + candidate;
                }
            }
            if (error.has("details") && error.get("details").isJsonObject()) {
                JsonObject details = error.getAsJsonObject("details");
                if (isString(details, "reason")) {
                    String candidate = details.get("reason").getAsString();
                    if (candidate.matches("[a-z0-9-]{1,80}")) {
                        reason = " reason=" + candidate;
                    }
                }
            }
        } catch (RuntimeException ignored) {
            // Malformed errors still produce a safe status and actionable guidance.
        }

        String guidance = switch (response.statusCode()) {
            case 401 -> "Reconnect or replace revoked authorization; do not retry this operation blindly.";
            case 409 -> "Keep input, read current state and review the conflict before a new guarded update.";
            case 423 -> "Keep generated input. Content is temporarily read-only; wait for conversion, then review current revision before deliberately retrying.";
            case 429 -> "Retry budget exhausted or write refused. Keep input and retry later deliberately.";
            default -> "Request refused. Keep input and inspect permissions or server state without logging response data.";
        };
        String requestId = response.headers().firstValue("x-request-id").orElse("");
        String trace = requestId.matches("[A-Za-z0-9_.:-]{1,128}") ? " requestId=" + requestId : "";
        return new ExampleFailure("HTTP " + response.statusCode() + code + reason + trace + ": " + guidance);
    }

    private static boolean isString(JsonObject object, String key) {
        return object.has(key) && object.get(key).isJsonPrimitive()
                && object.get(key).getAsJsonPrimitive().isString();
    }
}
