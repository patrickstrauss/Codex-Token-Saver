using System;
using System.Diagnostics;
using System.IO;
using System.Threading;

internal static class TrayLauncher
{
    private static void Log(string root, string message)
    {
        try
        {
            Directory.CreateDirectory(Path.Combine(root, "logs"));
            File.AppendAllText(Path.Combine(root, "logs", "tray-launcher.log"),
                DateTimeOffset.Now.ToString("o") + " " + message + Environment.NewLine);
        }
        catch { } // A logging failure must not stop service recovery.
    }

    private static int Main(string[] args)
    {
        string root = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ".."));
        try
        {
            if (args.Length > 1 || (args.Length == 1 && args[0] != "-OpenDashboard"))
                throw new ArgumentException("Only -OpenDashboard is supported.");
            string script = Path.Combine(root, "Tray.ps1");
            if (!File.Exists(script)) throw new FileNotFoundException("Tray.ps1 is missing.");
            string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
                "WindowsPowerShell", "v1.0", "powershell.exe");
            string arguments = "-NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + script + "\"";
            var start = new ProcessStartInfo(powershell);
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WorkingDirectory = root;
            // Task Scheduler recovery may not run for a manually started instance.
            // Keep transient tray failures from leaving the app without a recovery timer.
            for (int attempt = 1; attempt <= 3; attempt++)
            {
                start.Arguments = arguments + (attempt == 1 && args.Length == 1 ? " -OpenDashboard" : "");
                using (Process process = Process.Start(start))
                {
                    if (process == null) throw new InvalidOperationException("Windows did not start the tray.");
                    Log(root, "Tray started; PID " + process.Id + "; attempt " + attempt + ".");
                    process.WaitForExit();
                    Log(root, "Tray PID " + process.Id + " exited with exit code " + process.ExitCode + ".");
                    // The Quit menu and duplicate-instance checks both return zero.
                    if (process.ExitCode == 0) return 0;
                    if (attempt == 3)
                    {
                        Log(root, "Recovery limit reached; open Codex Token Saver to retry.");
                        return process.ExitCode;
                    }
                }
                Log(root, "Restarting tray in 2 seconds after unexpected exit.");
                Thread.Sleep(2000);
            }
            return 1;
        }
        catch (Exception exception)
        {
            Log(root, exception.Message);
            return 1;
        }
    }
}
