try
{
    if (args.Length != 1)
    {
        throw new ExampleError("Choose 01, 02, 03, 04, 05, 06 or webhook.");
    }
    if (args[0] == "webhook")
    {
        await WebhookReceiver.RunAsync();
    }
    else
    {
        await ReportExamples.RunAsync(args[0]);
    }
}
catch (ExampleError error)
{
    Console.Error.WriteLine(error.Message);
    Environment.ExitCode = 1;
}
catch (Exception)
{
    // Never echo raw server responses, credentials, document text or platform paths.
    Console.Error.WriteLine("Operation failed. Keep the input and local mapping; reconcile any uncertain write before another attempt.");
    Environment.ExitCode = 1;
}
