using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.ComponentModel;

// Native boundary: no cmd.exe parsing and no encoded/hidden shell commands.
internal static class HeadroomLauncher
{
    private static string QuoteArgument(string value)
    {
        var result = new StringBuilder("\"");
        int backslashes = 0;
        foreach (char character in value)
        {
            if (character == '\\') { backslashes++; continue; }
            if (character == '"')
            {
                result.Append('\\', backslashes * 2 + 1);
                result.Append('"');
            }
            else
            {
                result.Append('\\', backslashes);
                result.Append(character);
            }
            backslashes = 0;
        }
        result.Append('\\', backslashes * 2);
        result.Append('"');
        return result.ToString();
    }

    private static ProcessStartInfo OriginalStart(string[] args)
    {
        int offset = 0;
        if (args.Length > offset && args[offset] == "--exact") offset++;
        if (args.Length <= offset || args[offset] != "--")
            throw new ArgumentException("Expected -- followed by the original absolute executable.");
        offset++;
        if (args.Length <= offset || !Path.IsPathRooted(args[offset]) ||
            !String.Equals(Path.GetExtension(args[offset]), ".exe", StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException("The original command must be an absolute .exe path.");
        string executable = args[offset++];
        var arguments = new StringBuilder();
        for (; offset < args.Length; offset++)
        {
            if (arguments.Length > 0) arguments.Append(' ');
            arguments.Append(QuoteArgument(args[offset]));
        }
        var start = new ProcessStartInfo(executable, arguments.ToString());
        start.UseShellExecute = false;
        return start;
    }

    private static int Main(string[] args)
    {
        try
        {
            string root = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ".."));
            string executable = Path.Combine(root, "headroom", ".venv", "Scripts", "python.exe");
            string runner = Path.Combine(root, "headroom_run.py");
            Process child;
            if (!File.Exists(executable) || !File.Exists(runner))
            {
                // A removal between hook approval and execution must not break
                // the original command. This fallback is only before any child
                // starts; a failed/crashed Python child is never retried.
                child = Process.Start(OriginalStart(args));
            }
            else
            {
                var arguments = new StringBuilder(QuoteArgument(runner));
                foreach (string argument in args)
                    arguments.Append(' ').Append(QuoteArgument(argument));
                var start = new ProcessStartInfo(executable, arguments.ToString());
                start.UseShellExecute = false;
                try { child = Process.Start(start); }
                catch (Win32Exception)
                {
                    // CreateProcess failed before a child existed (for example,
                    // a damaged Python executable). Only this boundary can fall
                    // back; errors after successful startup are never retried.
                    child = Process.Start(OriginalStart(args));
                }
                if (child == null) child = Process.Start(OriginalStart(args));
            }
            // Keep cwd, stdin and both output streams inherited. The Python
            // runner decides whether captured command output can be compressed.
            using (Process process = child)
            {
                if (process == null) throw new InvalidOperationException("Windows did not start Headroom.");
                process.WaitForExit();
                return process.ExitCode;
            }
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("Codex Token Saver: could not start Headroom: " + error.Message);
            return 1;
        }
    }
}
