package com.markdownlogic.examples;

import com.google.gson.JsonObject;
import java.io.IOException;
import java.net.URI;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Set;

/** Stable resource IDs and private create journals for this single-process demonstration. */
final class ReportState {
    private final Path directory;
    private final JsonObject mapping;

    ReportState() throws IOException {
        directory = ExampleConfig.stateDirectory();
        PrivateFiles.createDirectory(directory);
        Path file = file("state.json");
        if (Files.isSymbolicLink(file)) {
            throw new ExampleFailure("State must not be a symbolic link.");
        }
        try {
            mapping = Files.exists(file) ? JsonSupport.parseObject(Files.readAllBytes(file)) : new JsonObject();
        } catch (RuntimeException exception) {
            throw new ExampleFailure("State file must contain a JSON object. Review the saved mapping before continuing.");
        }
    }

    Path file(String name) {
        return directory.resolve(name);
    }

    boolean has(String key) {
        return mapping.has(key);
    }

    String projectPath() {
        return "/api/v1/projects/" + ExampleConfig.encode(JsonSupport.requiredText(mapping, "projectId"));
    }

    String documentPath() {
        return projectPath() + "/documents/"
                + ExampleConfig.encode(JsonSupport.requiredText(mapping, "documentId"));
    }

    void put(String key, String value) {
        mapping.addProperty(key, value);
    }

    void save() throws IOException {
        PrivateFiles.replace(file("state.json"), JsonSupport.bytes(mapping));
    }

    /** Persist the exact target and payload before a create can reach the network. */
    void beginCreate(String scenario, URI origin, String path, JsonObject payload) throws IOException {
        Path pending = file("pending-" + scenario + ".json");
        if (Files.exists(pending, LinkOption.NOFOLLOW_LINKS)) {
            throw new ExampleFailure("A previous create may have reached the server. Keep the pending file and reconcile before creating again.");
        }

        // CREATE_NEW coordinates local repeats; this is not an API idempotency key.
        FileChannel output;
        try {
            output = FileChannel.open(pending,
                    Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE),
                    PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        } catch (UnsupportedOperationException exception) {
            output = FileChannel.open(pending, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
        }
        try (FileChannel channel = output) {
            JsonObject operation = JsonSupport.object("apiOrigin", origin.toString(),
                    "method", "POST", "path", path);
            operation.add("body", payload);
            ByteBuffer bytes = ByteBuffer.wrap(JsonSupport.bytes(operation));
            while (bytes.hasRemaining()) {
                channel.write(bytes);
            }
            channel.force(true);
        }
    }

    /** Clear only after a valid response and its mapping/result have been saved. */
    void completeCreate(String scenario) throws IOException {
        Files.delete(file("pending-" + scenario + ".json"));
    }

    static String readInput(String fallback) throws IOException {
        Path input = Path.of(ExampleConfig.environment("MDLOGIC_INPUT", fallback));
        // readString rejects malformed UTF-8 and keeps original line endings intact.
        String content = Files.readString(input, StandardCharsets.UTF_8);
        if (content.isEmpty()) {
            throw new ExampleFailure("The generated report must contain text.");
        }
        return content;
    }
}
