package com.markdownlogic.examples;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.gson.JsonElement;
import com.google.gson.JsonParser;
import java.nio.charset.StandardCharsets;

/** Small JSON conveniences; response fields are checked before updating local state. */
final class JsonSupport {
    private static final Gson JSON = new GsonBuilder().setPrettyPrinting().create();

    private JsonSupport() {
    }

    static byte[] bytes(JsonObject value) {
        return JSON.toJson(value).getBytes(StandardCharsets.UTF_8);
    }

    /** Refuse malformed envelopes without including their private contents in an error. */
    static JsonObject parseObject(byte[] bytes) {
        try {
            JsonElement value = JsonParser.parseString(new String(bytes, StandardCharsets.UTF_8));
            if (value.isJsonObject()) {
                return value.getAsJsonObject();
            }
        } catch (RuntimeException ignored) {
            // Report shape failures without exposing a response body or parser exception.
        }
        throw new ExampleFailure("Expected a JSON object. Keep pending files and reconcile before another mutation.");
    }

    /** Select a nested response object without relying on Gson's coercing accessors. */
    static JsonObject requiredObject(JsonObject parent, String key) {
        if (parent == null || !parent.has(key) || !parent.get(key).isJsonObject()) {
            throw new ExampleFailure("Required response object is missing. Keep pending files and reconcile before continuing.");
        }
        return parent.getAsJsonObject(key);
    }

    /** Require an actual nonempty JSON string, rather than coercing numbers or booleans. */
    static String requiredText(JsonObject object, String key) {
        if (object == null || !object.has(key) || !object.get(key).isJsonPrimitive()
                || !object.get(key).getAsJsonPrimitive().isString()
                || object.get(key).getAsString().isEmpty()) {
            throw new ExampleFailure("Required response or mapping field is missing. Reconcile state before continuing.");
        }
        return object.get(key).getAsString();
    }

    static JsonObject object(Object... pairs) {
        JsonObject result = new JsonObject();
        for (int index = 0; index < pairs.length; index += 2) {
            result.add((String) pairs[index], JSON.toJsonTree(pairs[index + 1]));
        }
        return result;
    }

    static void print(JsonObject value) {
        System.out.println(JSON.toJson(value));
    }
}
