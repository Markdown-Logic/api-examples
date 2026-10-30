#!/usr/bin/env bash
# Container entry point. The shared adapter mounts source at /src and caches at /cache.
set -euo pipefail

gson_jar=/cache/maven/com/google/code/gson/gson/2.13.2/gson-2.13.2.jar
classes_directory=/tmp/classes
mkdir -p "$classes_directory"

# Compile into the container's temporary storage; the source mount stays read-only.
javac --release 17 --add-modules jdk.httpserver \
  -cp "$gson_jar" \
  -d "$classes_directory" \
  java/src/main/java/com/markdownlogic/examples/*.java

# IPv4 supports the host-loopback test adapter. API origins still require HTTPS.
exec java -Djava.net.preferIPv4Stack=true --add-modules jdk.httpserver \
  -cp "$classes_directory:$gson_jar" \
  com.markdownlogic.examples.ReportExamples "$@"
