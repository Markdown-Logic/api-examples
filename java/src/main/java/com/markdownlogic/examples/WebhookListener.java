package com.markdownlogic.examples;

import com.google.gson.JsonObject;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Set;
import java.util.concurrent.Executors;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/** Authenticate deliveries and accept complete envelopes into a deduplicated local inbox. */
final class WebhookListener {
    private static final int MAX_BODY_BYTES = 1024 * 1024;
    private static final int CLOCK_TOLERANCE_SECONDS = 300;
    private final String secret;
    private final Path inbox;

    private WebhookListener(Path directory) throws IOException {
        secret = ExampleConfig.required("MDLOGIC_WEBHOOK_SECRET");
        PrivateFiles.createDirectory(directory);
        inbox = directory.resolve("inbox");
        PrivateFiles.createDirectory(inbox);
    }

    static void start() throws IOException {
        WebhookListener listener = new WebhookListener(ExampleConfig.stateDirectory());
        int port = configuredPort();
        String bind = ExampleConfig.environment("MDLOGIC_WEBHOOK_BIND", "127.0.0.1");
        if (!Set.of("127.0.0.1", "0.0.0.0").contains(bind)) {
            throw new ExampleFailure("Invalid webhook bind address.");
        }

        HttpServer server = HttpServer.create(new InetSocketAddress(bind, port), 16);
        // Serialize the small file-inbox demonstration; business work belongs in a worker.
        server.setExecutor(Executors.newSingleThreadExecutor());
        server.createContext("/", listener::handle);
        server.start();
        System.out.println("Java webhook inbox listening on " + bind + ":" + port + "/webhook");
    }

    private static int configuredPort() {
        try {
            int port = Integer.parseInt(ExampleConfig.environment("PORT", "8080"));
            if (port < 1 || port > 65535) {
                throw new NumberFormatException();
            }
            return port;
        } catch (NumberFormatException exception) {
            throw new ExampleFailure("PORT must be an integer from 1 to 65535.");
        }
    }

    private void handle(HttpExchange exchange) throws IOException {
        try {
            if (!exchange.getRequestURI().getPath().equals("/webhook")) {
                reply(exchange, 404);
                return;
            }
            if (!exchange.getRequestMethod().equals("POST")) {
                reply(exchange, 405);
                return;
            }

            byte[] raw = exchange.getRequestBody().readNBytes(MAX_BODY_BYTES + 1);
            if (raw.length > MAX_BODY_BYTES) {
                reply(exchange, 413);
                return;
            }
            String signature = exchange.getRequestHeaders().getFirst("MDL-Signature");
            if (!verifySignature(signature, raw, secret, Instant.now().getEpochSecond())) {
                reply(exchange, 401);
                return;
            }

            // Parse only after authenticating the exact bytes; reserialized JSON changes the HMAC.
            JsonObject event;
            String id;
            String type;
            try {
                event = JsonSupport.parseObject(raw);
                id = JsonSupport.requiredText(event, "id");
                type = JsonSupport.requiredText(event, "type");
            } catch (RuntimeException exception) {
                reply(exchange, 400);
                return;
            }
            String headerId = exchange.getRequestHeaders().getFirst("MDL-Event-Id");
            String headerType = exchange.getRequestHeaders().getFirst("MDL-Event-Type");
            if (!id.equals(headerId) || (headerType != null && !type.equals(headerType))) {
                reply(exchange, 400);
                return;
            }

            boolean duplicate = acceptEnvelope(id, raw);
            reply(exchange, duplicate ? 200 : 202);
        } catch (Exception exception) {
            // Leave failed deliveries retryable; do not leak body contents in an error response.
            reply(exchange, 500);
        } finally {
            exchange.close();
        }
    }

    /** Publish a fully flushed record without replacing an earlier accepted event. */
    private boolean acceptEnvelope(String id, byte[] raw) throws IOException, GeneralSecurityException {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(id.getBytes(StandardCharsets.UTF_8));
        Path target = inbox.resolve(HexFormat.of().formatHex(digest) + ".json");
        Path pending = PrivateFiles.temporaryFile(inbox, ".json");
        try {
            PrivateFiles.writeAndSync(pending, raw);
            try {
                // The signed event ID stays stable across retries. The exclusive link
                // prevents concurrent deliveries from accepting the same event twice.
                Files.createLink(target, pending);
                return false;
            } catch (FileAlreadyExistsException exception) {
                return true;
            }
        } finally {
            Files.deleteIfExists(pending);
        }
    }

    /** Check timestamp freshness and any rotating v1 signature in constant time. */
    static boolean verifySignature(String header, byte[] raw, String secret, long nowSeconds) {
        if (header == null) {
            return false;
        }
        try {
            String timestamp = null;
            List<String> signatures = new ArrayList<>();
            for (String part : header.split(",")) {
                String value = part.trim();
                if (value.startsWith("t=") && timestamp == null) {
                    timestamp = value.substring(2);
                }
                if (value.startsWith("v1=")) {
                    signatures.add(value.substring(3));
                }
            }
            if (timestamp == null || !timestamp.matches("[0-9]+")) {
                return false;
            }
            long seconds = Long.parseLong(timestamp);
            if (seconds <= 0 || seconds > nowSeconds + CLOCK_TOLERANCE_SECONDS
                    || seconds < nowSeconds - CLOCK_TOLERANCE_SECONDS) {
                return false;
            }

            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            // Parsing is only for freshness. Authenticate the exact timestamp text.
            mac.update((timestamp + ".").getBytes(StandardCharsets.US_ASCII));
            byte[] expected = mac.doFinal(raw);
            for (String signature : signatures) {
                if (signature.matches("[0-9a-f]{64}")
                        && MessageDigest.isEqual(expected, HexFormat.of().parseHex(signature))) {
                    return true;
                }
            }
        } catch (RuntimeException | GeneralSecurityException ignored) {
            // Invalid numbers, malformed signatures and cryptography failures refuse delivery.
        }
        return false;
    }

    private static void reply(HttpExchange exchange, int status) throws IOException {
        exchange.sendResponseHeaders(status, -1);
    }
}
