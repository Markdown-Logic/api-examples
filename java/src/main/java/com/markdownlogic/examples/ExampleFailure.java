package com.markdownlogic.examples;

/** A deliberately sanitized error message that is safe to show to the caller. */
final class ExampleFailure extends RuntimeException {
    private static final long serialVersionUID = 1L;

    ExampleFailure(String message) {
        super(message);
    }
}
