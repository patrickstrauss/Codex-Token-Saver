using System;
using System.Diagnostics;
using System.IO;

internal static class TrayLauncher
{
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
            var start = new ProcessStartInfo(powershell,
                "-NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + script + "\"" +
                (args.Length == 1 ? " -OpenDashboard" : ""));
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WorkingDirectory = root;
            using (Process process = Process.Start(start))
            {
                if (process == null) throw new InvalidOperationException("Windows did not start the tray.");
                process.WaitForExit();
                return process.ExitCode;
            }
        }
        catch (Exception exception)
        {
            try
            {
                Directory.CreateDirectory(Path.Combine(root, "logs"));
                File.AppendAllText(Path.Combine(root, "logs", "tray-launcher.log"),
                    DateTimeOffset.Now.ToString("o") + " " + exception.Message + Environment.NewLine);
            }
            catch { }
            return 1;
        }
    }
}
