package com.markdownlogic.examples;

import java.net.URI;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.Set;

/** Environment settings shared by the command-line examples and local receiver. */
final class ExampleConfig {
    private ExampleConfig() {
    }

    static String environment(String key, String fallback) {
        String value = System.getenv(key);
        return value == null || value.isBlank() ? fallback : value;
    }

    static Path stateDirectory() {
        return Path.of(environment("MDLOGIC_STATE_DIR", ".local/java"));
    }

    static String required(String key) {
        String value = System.getenv(key);
        if (value == null || value.isBlank()) {
            throw new ExampleFailure("Missing " + key + ". See java/README.md.");
        }
        return value;
    }

    /** Validate an origin before attaching credentials; plaintext is only for local tests. */
    static URI checkedOrigin(String value) {
        URI uri = URI.create(value);
        String host = uri.getHost();
        boolean local = Set.of("localhost", "127.0.0.1", "[::1]", "::1")
                .contains(host == null ? "" : host);
        boolean secureScheme = "https".equals(uri.getScheme());
        boolean localHttp = "http".equals(uri.getScheme()) && local;
        boolean originPath = uri.getRawPath().isEmpty() || uri.getRawPath().equals("/");
        if (host == null || !(secureScheme || localHttp) || !originPath
                || uri.getUserInfo() != null || uri.getRawQuery() != null
                || uri.getRawFragment() != null) {
            throw new ExampleFailure("API and OAuth settings must be HTTPS origins; HTTP is allowed only for literal localhost loopback.");
        }
        return uri;
    }

    /** Escape an opaque ID as one path segment, or a value in the OAuth form body. */
    static String encode(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8).replace("+", "%20");
    }
}
