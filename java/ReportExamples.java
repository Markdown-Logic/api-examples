import com.google.gson.*;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.io.IOException;
import java.math.BigInteger;
import java.net.*;
import java.net.http.*;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.*;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.concurrent.*;

/** Six small report scenarios. This is an example application, not an SDK. */
public final class ReportExamples {
    private static final Gson JSON = new GsonBuilder().setPrettyPrinting().create();
    private static final String[] EVENTS = {"document.created", "document.updated", "project.created", "project.updated", "share.created"};
    private final Path stateDir;
    private final JsonObject state;
    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(15))
            .followRedirects(HttpClient.Redirect.NEVER).build();
    private URI origin;
    private String token;

    private ReportExamples() throws IOException {
        stateDir = Path.of(env("MDLOGIC_STATE_DIR", ".local/java"));
        privateDirectory(stateDir);
        Path stateFile = stateDir.resolve("state.json");
        if (Files.isSymbolicLink(stateFile)) throw new IllegalArgumentException("State must not be a symbolic link.");
        state = Files.exists(stateFile) ? JsonParser.parseString(Files.readString(stateFile)).getAsJsonObject() : new JsonObject();
    }

    public static void main(String[] args) {
        try {
            if (args.length != 1 || !Set.of("01", "02", "03", "04", "05", "06", "webhook").contains(args[0])) {
                throw new SafeFailure("Usage: bash java/run.sh 01|02|03|04|05|06|webhook (from repository root)");
            }
            ReportExamples app = new ReportExamples();
            if (args[0].equals("webhook")) { app.receiveWebhooks(); return; }
            app.origin = checkedOrigin(env("MDLOGIC_API_ORIGIN", "https://api.markdownlogic.com"));
            app.token = app.accessToken();
            switch (args[0]) {
                case "01" -> app.project();
                case "02" -> app.createReport();
                case "03" -> app.updateReport();
                case "04" -> app.exportReport();
                case "05" -> app.shareReport();
                case "06" -> app.registerWebhook();
            }
        } catch (SafeFailure e) {
            System.err.println(e.getMessage());
            System.exit(1);
        } catch (Exception e) {
            // Do not print exception objects: URLs, response data and local paths can contain secrets.
            System.err.println("Local operation failed. Keep input and mapping files. Reconcile any uncertain write before trying again.");
            System.exit(1);
        }
    }

    // 01 — Provision once, list a bounded page, then update project metadata.
    private void project() throws Exception {
        if (state.has("projectId")) throw new SafeFailure("A project is already mapped. Reuse it; do not create another blindly.");
        String team = segment(required("MDLOGIC_TEAM"));
        JsonObject payload = object("name", "Report integration example", "mode", "document");
        String path = "/api/v1/teams/" + team + "/projects";
        pending("01", path, payload);
        JsonObject created = api("POST", path, payload);
        String id = text(created.getAsJsonObject("project"), "id");
        state.addProperty("projectId", id); saveState(); // Save before any later request can fail.
        Files.delete(stateDir.resolve("pending-01.json"));
        JsonObject page = api("GET", "/api/v1/teams/" + team + "/projects?limit=50&offset=0", null);
        api("PATCH", "/api/v1/projects/" + segment(id), object("name", "Report integration example"));
        print(object("scenario", "01", "projectId", id, "listed", page.getAsJsonArray("items").size()));
    }

    // 02 — The deterministic report name and create-only flag prevent accidental replacement.
    private void createReport() throws Exception {
        if (state.has("documentId")) throw new SafeFailure("A report is already mapped. Use scenario 03 to update it.");
        String content = input("fixtures/report.md");
        String path = projectPath() + "/artifacts";
        JsonObject payload = object("name", "report.md", "content", content, "format", "markdown", "ifNotExists", true);
        pending("02", path, payload);
        JsonObject result = api("POST", path, payload);
        JsonObject document = result.getAsJsonObject("artifact");
        state.addProperty("documentId", text(document, "id"));
        state.addProperty("revision", text(document, "revision")); saveState();
        Files.delete(stateDir.resolve("pending-02.json"));
        print(object("scenario", "02", "documentId", text(document, "id"), "decision", text(result, "decision")));
    }

    // 03 — Read once and carry that exact opaque revision into the write.
    private void updateReport() throws Exception {
        String content = input("fixtures/report-updated.md");
        String path = documentPath();
        JsonObject current = api("GET", path, null).getAsJsonObject("document");
        // This synthetic example deliberately replaces the report. A real UI reviews current.content here.
        JsonObject result = api("PUT", path, object("content", content, "expectedRevision", text(current, "revision"),
                "changeNote", "Refresh generated report"));
        JsonObject updated = result.getAsJsonObject("document");
        state.addProperty("revision", text(updated, "revision")); saveState();
        print(object("scenario", "03", "documentId", text(updated, "id"), "decision", text(result, "decision")));
    }

    // 04 — Inspect one history page and export only when explicitly invoked.
    private void exportReport() throws Exception {
        String path = documentPath();
        JsonObject page = api("GET", path + "/versions?limit=20&offset=0", null);
        if (!page.has("items") || !page.get("items").isJsonArray() || !page.has("hasMore") || !page.get("hasMore").isJsonPrimitive() || !page.get("hasMore").getAsJsonPrimitive().isBoolean()) throw new SafeFailure("Malformed history page; export stopped.");
        JsonArray items = page.getAsJsonArray("items");
        if (!items.isEmpty()) api("GET", path + "/versions/" + segment(text(items.get(0).getAsJsonObject(), "id")), null);
        byte[] html = request("GET", origin.resolve(path + "/renders/html"), null, "application/json", true).body();
        writePrivate(stateDir.resolve("report.html"), html);
        print(object("scenario", "04", "versionsListed", items.size(), "hasMore", page.get("hasMore").getAsBoolean(),
                "exportFile", stateDir.resolve("report.html").toString()));
    }

    // 05 — An explicit user action; the private share URL stays out of routine logs.
    private void shareReport() throws Exception {
        if (Files.exists(stateDir.resolve("share.json"))) throw new SafeFailure("A share is already saved. Review it before creating another.");
        String path = documentPath() + "/shares";
        JsonObject payload = object("expiresInDays", 30);
        pending("05", path, payload);
        JsonObject result = api("POST", path, payload);
        writePrivate(stateDir.resolve("share.json"), JSON.toJson(result).getBytes(StandardCharsets.UTF_8));
        String id = text(result.getAsJsonObject("share"), "id");
        text(result.getAsJsonObject("share"), "url");
        Files.delete(stateDir.resolve("pending-05.json"));
        print(object("scenario", "05", "shareId", id,
                "shareFile", stateDir.resolve("share.json").toString()));
    }

    // 06 — Administrative setup, separate from ordinary third-party user consent.
    private void registerWebhook() throws Exception {
        if (Files.exists(stateDir.resolve("webhook.json"))) throw new SafeFailure("A webhook response is already saved. Reuse or rotate it rather than registering again.");
        String team = segment(required("MDLOGIC_TEAM"));
        String callback = required("MDLOGIC_WEBHOOK_URL");
        URI uri = URI.create(callback);
        if (!"https".equals(uri.getScheme()) || uri.getHost() == null || uri.getUserInfo() != null || uri.getFragment() != null)
            throw new SafeFailure("MDLOGIC_WEBHOOK_URL must be an HTTPS receiver URL without userinfo or fragment.");
        JsonArray catalogue = api("GET", "/api/v1/webhooks/events", null).getAsJsonArray("events");
        for (String name : EVENTS) if (!catalogue.contains(new JsonPrimitive(name)))
            throw new SafeFailure("The server event catalogue does not support the example subscription.");
        JsonObject payload = object("url", callback, "description", "Generated report lifecycle");
        payload.add("events", JSON.toJsonTree(EVENTS));
        String path = "/api/v1/teams/" + team + "/webhooks";
        pending("06", path, payload);
        JsonObject result = api("POST", path, payload);
        writePrivate(stateDir.resolve("webhook.json"), JSON.toJson(result).getBytes(StandardCharsets.UTF_8));
        String id = text(result.getAsJsonObject("webhook"), "id");
        text(result, "secret");
        Files.delete(stateDir.resolve("pending-06.json"));
        print(object("scenario", "06", "webhookId", id,
                "secretFile", stateDir.resolve("webhook.json").toString()));
    }

    private String accessToken() throws Exception {
        String supplied = System.getenv("MDLOGIC_TOKEN");
        if (supplied != null && !supplied.isBlank()) return supplied;
        URI issuer = checkedOrigin(env("MDLOGIC_OAUTH_ISSUER", "https://auth.markdownlogic.com"));
        String form = "grant_type=client_credentials&client_id=" + segment(required("MDLOGIC_CLIENT_ID"))
                + "&client_secret=" + segment(required("MDLOGIC_CLIENT_SECRET"))
                + "&scope=" + segment("projects:read documents:read documents:write");
        HttpResponse<byte[]> response = request("POST", issuer.resolve("/oauth/token"), form.getBytes(StandardCharsets.UTF_8),
                "application/x-www-form-urlencoded", false);
        return text(parseObject(response.body()), "access_token");
    }

    private JsonObject api(String method, String path, JsonObject body) throws Exception {
        byte[] payload = body == null ? null : JSON.toJson(body).getBytes(StandardCharsets.UTF_8);
        return parseObject(request(method, origin.resolve(path), payload, "application/json", true).body());
    }

    private HttpResponse<byte[]> request(String method, URI uri, byte[] body, String contentType, boolean authenticated) throws Exception {
        for (int attempt = 0; attempt < 3; attempt++) {
            HttpRequest.Builder builder = HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(15))
                    .header("Accept", "application/json");
            if (authenticated) builder.header("Authorization", "Bearer " + token);
            if (body != null) builder.header("Content-Type", contentType);
            builder.method(method, body == null ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofByteArray(body));
            CompletableFuture<HttpResponse<byte[]>> future = http.sendAsync(builder.build(), HttpResponse.BodyHandlers.ofByteArray());
            HttpResponse<byte[]> response;
            try { response = future.get(15, TimeUnit.SECONDS); }
            catch (InterruptedException e) {
                future.cancel(true);
                Thread.currentThread().interrupt();
                throw new SafeFailure("Request interrupted. Keep input and reconcile an uncertain write before another attempt.");
            } catch (ExecutionException | TimeoutException e) {
                future.cancel(true);
                throw new SafeFailure(method.equals("GET") ? "Read failed or timed out. No automatic network retry."
                        : "Write outcome is uncertain. Keep input; reconcile current server state before another write.");
            }
            int status = response.statusCode();
            if (status == 429 && method.equals("GET") && attempt < 2) {
                long delay = retryDelay(response.headers().firstValue("Retry-After").orElse(null), attempt);
                if (delay > 5000) throw new SafeFailure("HTTP 429: server wait exceeds this example's five-second retry budget. Retry later.");
                if (delay < 5000) delay += ThreadLocalRandom.current().nextLong(1, Math.min(100, 5000 - delay) + 1);
                try { Thread.sleep(delay); }
                catch (InterruptedException e) { Thread.currentThread().interrupt(); throw new SafeFailure("Read retry interrupted; no further request was sent."); }
                continue;
            }
            if (status < 200 || status >= 300) throw apiFailure(response);
            return response;
        }
        throw new AssertionError("unreachable");
    }

    private static long retryDelay(String value, int attempt) {
        if (value != null) {
            try {
                if (value.matches("[0-9]+")) {
                    BigInteger seconds = new BigInteger(value);
                    return seconds.compareTo(BigInteger.valueOf(5)) > 0 ? 5001 : seconds.longValue() * 1000;
                }
                long millis = Duration.between(Instant.now(), ZonedDateTime.parse(value, DateTimeFormatter.RFC_1123_DATE_TIME).toInstant()).toMillis();
                return Math.max(0, millis);
            } catch (RuntimeException ignored) { /* Invalid Retry-After uses the bounded fallback. */ }
        }
        return (1L << attempt) * 1000;
    }

    private static SafeFailure apiFailure(HttpResponse<byte[]> response) {
        String code = "", reason = "";
        try {
            JsonObject error = parseObject(response.body());
            if (error.has("code") && error.get("code").isJsonPrimitive() && error.get("code").getAsJsonPrimitive().isString() && error.get("code").getAsString().matches("[A-Z][A-Z0-9_]{0,63}")) code = " " + error.get("code").getAsString();
            if (error.has("details") && error.get("details").isJsonObject() && error.getAsJsonObject("details").has("reason") && error.getAsJsonObject("details").get("reason").isJsonPrimitive() && error.getAsJsonObject("details").get("reason").getAsJsonPrimitive().isString()) {
                String candidate = error.getAsJsonObject("details").get("reason").getAsString();
                if (candidate.matches("[a-z0-9-]{1,80}")) reason = " reason=" + candidate;
            }
        } catch (RuntimeException ignored) { /* Never print the raw body. */ }
        String guidance = switch (response.statusCode()) {
            case 401 -> "Reconnect or replace revoked authorization; do not retry this operation blindly.";
            case 409 -> "Keep input, read current state and review the conflict before a new guarded update.";
            case 423 -> "Keep generated input. Content is temporarily read-only; wait for conversion, then review current revision before deliberately retrying.";
            case 429 -> "Retry budget exhausted or write refused. Keep input and retry later deliberately.";
            default -> "Request refused. Keep input and inspect permissions or server state without logging response data.";
        };
        String requestId = response.headers().firstValue("x-request-id").orElse("");
        String trace = requestId.matches("[A-Za-z0-9_.:-]{1,128}") ? " requestId=" + requestId : "";
        return new SafeFailure("HTTP " + response.statusCode() + code + reason + trace + ": " + guidance);
    }

    private String projectPath() { return "/api/v1/projects/" + segment(text(state, "projectId")); }
    private String documentPath() { return projectPath() + "/documents/" + segment(text(state, "documentId")); }
    private void pending(String scenario, String path, JsonObject payload) throws IOException {
        Path file = stateDir.resolve("pending-" + scenario + ".json");
        if (Files.exists(file, LinkOption.NOFOLLOW_LINKS)) throw new SafeFailure("A previous create may have reached the server. Keep the pending file and reconcile before creating again.");
        // A local operation marker is application-side duplicate prevention, not server idempotency.
        FileChannel output;
        try { output = FileChannel.open(file, Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------"))); }
        catch (UnsupportedOperationException e) { output = FileChannel.open(file, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE); }
        try (FileChannel channel = output) {
            JsonObject operation = object("apiOrigin", origin.toString(), "method", "POST", "path", path);
            operation.add("body", payload);
            ByteBuffer bytes = ByteBuffer.wrap(JSON.toJson(operation).getBytes(StandardCharsets.UTF_8));
            while (bytes.hasRemaining()) channel.write(bytes);
            channel.force(true);
        }
    }
    private void saveState() throws IOException { writePrivate(stateDir.resolve("state.json"), JSON.toJson(state).getBytes(StandardCharsets.UTF_8)); }
    private static String input(String fallback) throws IOException {
        String text = Files.readString(Path.of(env("MDLOGIC_INPUT", fallback)), StandardCharsets.UTF_8);
        if (text.isEmpty()) throw new SafeFailure("The generated report must contain text.");
        return text;
    }
    private static URI checkedOrigin(String value) {
        URI uri = URI.create(value);
        String host = uri.getHost();
        boolean local = Set.of("localhost", "127.0.0.1", "[::1]", "::1").contains(host == null ? "" : host);
        if (host == null || !("https".equals(uri.getScheme()) || ("http".equals(uri.getScheme()) && local))
                || uri.getUserInfo() != null || uri.getRawQuery() != null || uri.getRawFragment() != null
                || !(uri.getRawPath().isEmpty() || uri.getRawPath().equals("/")))
            throw new SafeFailure("API and OAuth settings must be HTTPS origins; HTTP is allowed only for literal localhost loopback.");
        return uri;
    }
    private static String segment(String text) { return URLEncoder.encode(text, StandardCharsets.UTF_8).replace("+", "%20"); }
    private static String env(String key, String fallback) { String value = System.getenv(key); return value == null || value.isBlank() ? fallback : value; }
    private static String required(String key) { String value = System.getenv(key); if (value == null || value.isBlank()) throw new SafeFailure("Missing " + key + ". See java/README.md."); return value; }
    private static String text(JsonObject object, String key) {
        if (object == null || !object.has(key) || !object.get(key).isJsonPrimitive() || !object.get(key).getAsJsonPrimitive().isString()
                || object.get(key).getAsString().isEmpty()) throw new SafeFailure("Required response or mapping field is missing. Reconcile state before continuing.");
        return object.get(key).getAsString();
    }
    private static JsonObject parseObject(byte[] bytes) { return JsonParser.parseString(new String(bytes, StandardCharsets.UTF_8)).getAsJsonObject(); }
    private static JsonObject object(Object... pairs) {
        JsonObject result = new JsonObject();
        for (int i = 0; i < pairs.length; i += 2) result.add((String)pairs[i], JSON.toJsonTree(pairs[i + 1]));
        return result;
    }
    private static void print(JsonObject object) { System.out.println(JSON.toJson(object)); }
    private static void privateDirectory(Path directory) throws IOException {
        if (Files.isSymbolicLink(directory)) throw new SafeFailure("Private state directory must not be a symbolic link.");
        try { Files.createDirectories(directory, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------"))); }
        catch (UnsupportedOperationException e) { Files.createDirectories(directory); }
        try { Files.setPosixFilePermissions(directory, PosixFilePermissions.fromString("rwx------")); }
        catch (UnsupportedOperationException ignored) { /* Use a user-private directory with appropriate ACLs on Windows. */ }
    }
    private static void writePrivate(Path file, byte[] bytes) throws IOException {
        if (Files.isSymbolicLink(file)) throw new SafeFailure("Private file must not be a symbolic link.");
        Path temporary;
        try { temporary = Files.createTempFile(file.getParent(), ".pending-", ".tmp", PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------"))); }
        catch (UnsupportedOperationException e) { temporary = Files.createTempFile(file.getParent(), ".pending-", ".tmp"); }
        try {
            try (FileChannel channel = FileChannel.open(temporary, StandardOpenOption.WRITE)) {
                ByteBuffer buffer = ByteBuffer.wrap(bytes);
                while (buffer.hasRemaining()) channel.write(buffer);
                channel.force(true);
            }
            try { Files.move(temporary, file, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); }
            catch (AtomicMoveNotSupportedException e) { Files.move(temporary, file, StandardCopyOption.REPLACE_EXISTING); }
        } finally { Files.deleteIfExists(temporary); }
    }

    // Receive authenticated envelopes into a local inbox; no business side effects happen here.
    private void receiveWebhooks() throws IOException {
        String secret = required("MDLOGIC_WEBHOOK_SECRET");
        Path inbox = stateDir.resolve("inbox"); privateDirectory(inbox);
        int port;
        try { port = Integer.parseInt(env("PORT", "8080")); if (port < 1 || port > 65535) throw new NumberFormatException(); }
        catch (NumberFormatException e) { throw new SafeFailure("PORT must be an integer from 1 to 65535."); }
        String bind = env("MDLOGIC_WEBHOOK_BIND", "127.0.0.1");
        if (!Set.of("127.0.0.1", "0.0.0.0").contains(bind)) throw new SafeFailure("Invalid webhook bind address.");
        HttpServer server = HttpServer.create(new InetSocketAddress(bind, port), 16);
        // One worker keeps the small file-inbox example's commit/dedup sequence serialized.
        server.setExecutor(Executors.newSingleThreadExecutor());
        server.createContext("/", exchange -> {
            try {
                if (!exchange.getRequestURI().getPath().equals("/webhook")) { reply(exchange, 404); return; }
                if (!exchange.getRequestMethod().equals("POST")) { reply(exchange, 405); return; }
                byte[] raw = exchange.getRequestBody().readNBytes(1024 * 1024 + 1);
                if (raw.length > 1024 * 1024) { reply(exchange, 413); return; }
                if (!verify(exchange.getRequestHeaders().getFirst("MDL-Signature"), raw, secret, Instant.now().getEpochSecond())) {
                    reply(exchange, 401); return;
                }
                JsonObject event;
                try { event = parseObject(raw); }
                catch (RuntimeException e) { reply(exchange, 400); return; }
                String id, type;
                try { id = text(event, "id"); type = text(event, "type"); }
                catch (SafeFailure e) { reply(exchange, 400); return; }
                String headerType = exchange.getRequestHeaders().getFirst("MDL-Event-Type");
                if (!id.equals(exchange.getRequestHeaders().getFirst("MDL-Event-Id")) || (headerType != null && !type.equals(headerType))) {
                    reply(exchange, 400); return;
                }
                String key = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(id.getBytes(StandardCharsets.UTF_8)));
                Path target = inbox.resolve(key + ".json");
                // Write+force a complete temporary envelope, then publish it using a no-clobber hard link.
                // Readers never see a partial accepted record. Existing target means an accepted duplicate.
                Path pending;
                try { pending = Files.createTempFile(inbox, ".pending-", ".json", PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------"))); }
                catch (UnsupportedOperationException e) { pending = Files.createTempFile(inbox, ".pending-", ".json"); }
                boolean duplicate = false;
                try {
                    try (FileChannel channel = FileChannel.open(pending, StandardOpenOption.WRITE)) {
                        ByteBuffer buffer = ByteBuffer.wrap(raw); while (buffer.hasRemaining()) channel.write(buffer); channel.force(true);
                    }
                    try { Files.createLink(target, pending); }
                    catch (FileAlreadyExistsException e) { duplicate = true; }
                } finally { Files.deleteIfExists(pending); }
                reply(exchange, duplicate ? 200 : 202);
            } catch (Exception e) { reply(exchange, 500); }
            finally { exchange.close(); }
        });
        server.start();
        System.out.println("Java webhook inbox listening on 127.0.0.1:" + port + "/webhook");
    }

    static boolean verify(String header, byte[] raw, String secret, long nowSeconds) {
        if (header == null) return false;
        try {
            String timestamp = null;
            List<String> signatures = new ArrayList<>();
            for (String part : header.split(",")) {
                String value = part.trim();
                if (value.startsWith("t=") && timestamp == null) timestamp = value.substring(2);
                if (value.startsWith("v1=")) signatures.add(value.substring(3));
            }
            if (timestamp == null || !timestamp.matches("[0-9]+")) return false;
            long t = Long.parseLong(timestamp);
            if (t <= 0 || t > nowSeconds + 300 || t < nowSeconds - 300) return false;
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            mac.update((t + ".").getBytes(StandardCharsets.US_ASCII));
            byte[] expected = mac.doFinal(raw);
            for (String signature : signatures) {
                if (signature.matches("[0-9a-f]{64}") && MessageDigest.isEqual(expected, HexFormat.of().parseHex(signature))) return true;
            }
        } catch (RuntimeException | GeneralSecurityException ignored) { }
        return false;
    }
    private static void reply(HttpExchange exchange, int status) throws IOException { exchange.sendResponseHeaders(status, -1); }
    private static final class SafeFailure extends RuntimeException { private static final long serialVersionUID = 1L; SafeFailure(String message) { super(message); } }
}
