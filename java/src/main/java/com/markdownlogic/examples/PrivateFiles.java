package com.markdownlogic.examples;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;

/** Private local output with complete-file publication instead of partial overwrites. */
final class PrivateFiles {
    private PrivateFiles() {
    }

    static void createDirectory(Path directory) throws IOException {
        if (Files.isSymbolicLink(directory)) {
            throw new ExampleFailure("Private state directory must not be a symbolic link.");
        }
        try {
            Files.createDirectories(directory, PosixFilePermissions.asFileAttribute(
                    PosixFilePermissions.fromString("rwx------")));
        } catch (UnsupportedOperationException exception) {
            Files.createDirectories(directory);
        }
        try {
            Files.setPosixFilePermissions(directory, PosixFilePermissions.fromString("rwx------"));
        } catch (UnsupportedOperationException ignored) {
            // On Windows, configure user-only ACLs on the state directory before running.
        }
    }

    static Path temporaryFile(Path directory, String suffix) throws IOException {
        try {
            return Files.createTempFile(directory, ".pending-", suffix,
                    PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        } catch (UnsupportedOperationException exception) {
            return Files.createTempFile(directory, ".pending-", suffix);
        }
    }

    /** Flush the complete payload before another reader can observe its final filename. */
    static void writeAndSync(Path file, byte[] bytes) throws IOException {
        try (FileChannel channel = FileChannel.open(file, StandardOpenOption.WRITE)) {
            ByteBuffer buffer = ByteBuffer.wrap(bytes);
            while (buffer.hasRemaining()) {
                channel.write(buffer);
            }
            channel.force(true);
        }
    }

    static void replace(Path file, byte[] bytes) throws IOException {
        if (Files.isSymbolicLink(file)) {
            throw new ExampleFailure("Private file must not be a symbolic link.");
        }
        Path temporary = temporaryFile(file.getParent(), ".tmp");
        try {
            writeAndSync(temporary, bytes);
            try {
                Files.move(temporary, file, StandardCopyOption.ATOMIC_MOVE,
                        StandardCopyOption.REPLACE_EXISTING);
            } catch (AtomicMoveNotSupportedException exception) {
                Files.move(temporary, file, StandardCopyOption.REPLACE_EXISTING);
            }
        } finally {
            Files.deleteIfExists(temporary);
        }
    }
}
