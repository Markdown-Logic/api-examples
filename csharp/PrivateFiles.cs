using System.Text.Json;
using System.Text.Json.Nodes;

static class PrivateFiles
{
    const UnixFileMode DirectoryMode = UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute;
    const UnixFileMode FileModeBits = UnixFileMode.UserRead | UnixFileMode.UserWrite;

    public static string StateDirectory()
    {
        string path = Environment.GetEnvironmentVariable("MDLOGIC_STATE_DIR") ?? ".local/csharp";
        EnsureDirectory(path);
        return path;
    }

    public static void EnsureDirectory(string path)
    {
        if (OperatingSystem.IsWindows()) Directory.CreateDirectory(path);
        else
        {
            Directory.CreateDirectory(path, DirectoryMode);
            File.SetUnixFileMode(path, DirectoryMode);
        }
    }

    public static void WriteJson(string path, JsonNode node) => Write(path, JsonSerializer.SerializeToUtf8Bytes(node, new JsonSerializerOptions { WriteIndented = true }));

    // A complete private temporary file is made visible by one rename. On failure,
    // the existing mapping is left intact. Do not share one state dir among writers.
    public static void Write(string path, byte[] bytes)
    {
        string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            WriteNew(temporary, bytes);
            File.Move(temporary, path, true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }

    public static void WriteNew(string path, byte[] bytes)
    {
        var options = new FileStreamOptions { Mode = FileMode.CreateNew, Access = FileAccess.Write, Share = FileShare.None };
        if (!OperatingSystem.IsWindows()) options.UnixCreateMode = FileModeBits;
        using var file = new FileStream(path, options);
        file.Write(bytes);
        file.Flush(true);
    }
}
