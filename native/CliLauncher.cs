using System;
using System.Diagnostics;
using System.IO;
using System.Text;

// Preserve argv without a cmd.exe layer, including AST metavariables and quotes.
internal static class CliLauncher
{
    private static string Quote(string value)
    {
        var result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char ch in value)
        {
            if (ch == '\\') { slashes++; continue; }
            result.Append('\\', ch == '"' ? slashes * 2 + 1 : slashes);
            result.Append(ch);
            slashes = 0;
        }
        result.Append('\\', slashes * 2).Append('"');
        return result.ToString();
    }
    private static int Main(string[] args)
    {
        try
        {
            string root = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ".."));
            string name = Path.GetFileNameWithoutExtension(System.Reflection.Assembly.GetExecutingAssembly().Location);
            string component = name == "playwright-cli" ? "playwright_cli" : "ast_grep";
            var arguments = new StringBuilder(Quote(Path.Combine(root, "cli_tools.py"))).Append(' ').Append(component);
            foreach (string argument in args) arguments.Append(' ').Append(Quote(argument));
            var start = new ProcessStartInfo(Path.Combine(root, "headroom", ".venv", "Scripts", "python.exe"), arguments.ToString());
            start.UseShellExecute = false;
            using (Process child = Process.Start(start))
            {
                if (child == null) throw new InvalidOperationException("CLI process did not start.");
                child.WaitForExit();
                return child.ExitCode;
            }
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("Codex Token Saver: " + error.Message);
            return 127;
        }
    }
}
