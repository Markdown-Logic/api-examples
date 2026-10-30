#!/usr/bin/env bash
set -euo pipefail
# Invoke from repository root. Dependency fetching is an explicit setup step.
gson_jar="${GSON_JAR:-${HOME}/.m2/repository/com/google/code/gson/gson/2.13.2/gson-2.13.2.jar}"
if [[ ! -f "$gson_jar" ]]; then
  echo 'Gson 2.13.2 is missing. Follow java/README.md setup or set GSON_JAR.' >&2
  exit 1
fi
mkdir -p java/target/classes
javac --release 17 --add-modules jdk.httpserver -cp "$gson_jar" -d java/target/classes java/src/main/java/com/markdownlogic/examples/*.java
exec java --add-modules jdk.httpserver -cp "java/target/classes:$gson_jar" com.markdownlogic.examples.ReportExamples "$@"
