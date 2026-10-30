package com.markdownlogic.examples;

import java.util.Set;

/** Select one report task; each task lives in its own scenario class. */
public final class ReportExamples {
    private ReportExamples() {
    }

    public static void main(String[] args) {
        try {
            if (args.length != 1 || !Set.of("01", "02", "03", "04", "05", "06", "webhook").contains(args[0])) {
                throw new ExampleFailure("Usage: bash java/run.sh 01|02|03|04|05|06|webhook (from repository root)");
            }

            if (args[0].equals("webhook")) {
                WebhookListener.start();
                return;
            }

            ReportState state = new ReportState();
            ApiClient api = new ApiClient();
            switch (args[0]) {
                case "01" -> ProjectScenario.run(api, state);
                case "02" -> CreateReportScenario.run(api, state);
                case "03" -> UpdateReportScenario.run(api, state);
                case "04" -> ExportReportScenario.run(api, state);
                case "05" -> ShareReportScenario.run(api, state);
                case "06" -> RegisterWebhookScenario.run(api, state);
                default -> throw new AssertionError("Validated scenario missing from dispatcher.");
            }
        } catch (ExampleFailure exception) {
            System.err.println(exception.getMessage());
            System.exit(1);
        } catch (Exception exception) {
            // Exception objects can contain credentials, response text and private paths.
            System.err.println("Local operation failed. Keep input and mapping files. Reconcile any uncertain write before trying again.");
            System.exit(1);
        }
    }
}
