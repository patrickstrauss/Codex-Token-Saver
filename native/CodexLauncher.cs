using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;

internal static class CodexLauncher
{
    private static string QuoteArgument(string value)
    {
        var result = new StringBuilder("\"");
        int backslashes = 0;
        foreach (char character in value)
        {
            if (character == '\\')
            {
                backslashes++;
                continue;
            }
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

    private static int Main(string[] args)
    {
        try
        {
            string name = Path.GetFileNameWithoutExtension(Assembly.GetExecutingAssembly().Location);
            bool headroom = String.Equals(name, "codex-headroom", StringComparison.OrdinalIgnoreCase);
            if (!headroom && !String.Equals(name, "codex-saver", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Unrecognized CLI launcher name.");
            string root = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ".."));
            string python = Path.Combine(root, "dashboard", ".venv", "Scripts", "python.exe");
            string script = Path.Combine(root, "launch_codex.py");
            if (!File.Exists(python))
                throw new FileNotFoundException("Python runtime is missing: " + python);
            if (!File.Exists(script))
                throw new FileNotFoundException("CLI launcher script is missing: " + script);

            var arguments = new StringBuilder(QuoteArgument(script));
            if (headroom)
                arguments.Append(" --experimental-headroom");
            arguments.Append(" --");
            foreach (string argument in args)
            {
                arguments.Append(' ');
                arguments.Append(QuoteArgument(argument));
            }
            var start = new ProcessStartInfo(python, arguments.ToString());
            start.UseShellExecute = false;
            // Inherit the caller's directory and all standard streams. Python
            // owns routing decisions; this launcher only forwards arguments.
            using (Process process = Process.Start(start))
            {
                if (process == null)
                    throw new InvalidOperationException("Windows did not start the CLI launcher.");
                process.WaitForExit();
                return process.ExitCode;
            }
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine("Codex Token Saver: " + exception.Message);
            return 1;
        }
    }
}
