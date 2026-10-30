using System.Text.Json;
using System.Text.Json.Nodes;

/// <summary>Writes private state without exposing partially written replacement files.</summary>
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

    /// <summary>Applies Unix owner-only permissions; Windows callers must configure ACLs.</summary>
    public static void EnsureDirectory(string path)
    {
        if (OperatingSystem.IsWindows())
        {
            Directory.CreateDirectory(path);
        }
        else
        {
            Directory.CreateDirectory(path, DirectoryMode);
            File.SetUnixFileMode(path, DirectoryMode);
        }
    }

    public static void WriteJson(string path, JsonNode node)
    {
        var options = new JsonSerializerOptions { WriteIndented = true };
        Write(path, JsonSerializer.SerializeToUtf8Bytes(node, options));
    }

    /// <summary>Replaces a mapping only after the complete private temporary file is flushed.</summary>
    /// <remarks>Use one writer per state directory. A rename is not a database transaction.</remarks>
    public static void Write(string path, byte[] bytes)
    {
        string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            WriteNew(temporary, bytes);
            File.Move(temporary, path, true);
        }
        finally
        {
            if (File.Exists(temporary))
            {
                File.Delete(temporary);
            }
        }
    }

    /// <summary>Creates a new file exclusively, preserving existing pending-operation markers.</summary>
    public static void WriteNew(string path, byte[] bytes)
    {
        var options = new FileStreamOptions
        {
            Mode = FileMode.CreateNew,
            Access = FileAccess.Write,
            Share = FileShare.None
        };
        if (!OperatingSystem.IsWindows())
        {
            options.UnixCreateMode = FileModeBits;
        }

        using var file = new FileStream(path, options);
        file.Write(bytes);
        file.Flush(true);
    }
}
