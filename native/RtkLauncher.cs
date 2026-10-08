using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Collections.Generic;
using System.Threading;
using System.Web.Script.Serialization;

// A console executable avoids cmd.exe's second interpretation of PowerShell
// arguments. The actual RTK binary remains untouched in tools/rtk.exe.
internal static class RtkLauncher
{
    private const int MaxOutputBytes = 2 * 1024 * 1024;
    // Keep aligned with command_compression.MIN_OUTPUT_BYTES. Python makes
    // the final token/byte reduction decision including the recovery header.
    private const int MinOutputBytes = 1024;

    private static Dictionary<string, bool> Preferences(string root)
    {
        var values = new Dictionary<string, bool> {
            {"rtk", true}, {"headroom_local", true}, {"serena", false},
            {"playwright_cli", false}, {"ast_grep", false}, {"laya_router", false}
        };
        string path = Path.Combine(root, "settings", "components.json");
        try
        {
            string json;
            using (var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read | FileShare.Delete))
            {
                if (file.Length > 16384) throw new FormatException();
                using (var reader = new StreamReader(file, new UTF8Encoding(false, true), false)) json = reader.ReadToEnd();
                if (json.StartsWith("\uFEFF", StringComparison.Ordinal)) json = json.Substring(1);
            }
            var data = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(json);
            if (data == null || data.Count != 2 || !data.ContainsKey("schema_version") ||
                !(data["schema_version"] is int) || (int)data["schema_version"] != 1 ||
                !data.ContainsKey("components")) throw new FormatException();
            var components = data["components"] as Dictionary<string, object>;
            if (components == null) throw new FormatException();
            foreach (var entry in components)
            {
                // Accept old settings without exposing either retired feature.
                if (entry.Key == "local_summaries" || entry.Key == "llama_cpp")
                {
                    if (!(entry.Value is bool)) throw new FormatException();
                    continue;
                }
                if (!values.ContainsKey(entry.Key) || !(entry.Value is bool)) throw new FormatException();
                values[entry.Key] = (bool)entry.Value;
            }
        }
        catch (FileNotFoundException) { return values; }
        catch (DirectoryNotFoundException) { return values; }
        catch
        {
            // Malformed settings must not silently re-enable lossy filtering.
            foreach (string key in new List<string>(values.Keys)) values[key] = false;
        }
        return values;
    }

    private static string[] WithoutRtkCompression(string[] args)
    {
        if (args.Length == 0) return args;
        string command = args[0].ToLowerInvariant();
        if (Array.IndexOf(new[] { "gain", "help", "--help", "-h", "--version", "-V", "recall", "verify", "proxy" }, args[0]) >= 0)
            return args;
        // Only known external-command forms have an unchanged native argv.
        // RTK-only verbs and global flags need explicit handling, not token stripping.
        if (Array.IndexOf(new[] { "git", "rg", "cargo", "dotnet", "pytest", "uv", "npm", "npx", "pnpm", "go", "docker", "gh", "kubectl" }, command) < 0)
            throw new ArgumentException("RTK compression is off. Run the original external command directly for this RTK-only command.");
        var result = new string[args.Length + 1];
        result[0] = "proxy";
        Array.Copy(args, 0, result, 1, args.Length);
        return result;
    }

    // Optional compression never executes the command. RTK owns its original
    // invocation; if compression fails, the captured original is delivered.
    private sealed class OutputCapture
    {
        private readonly object sync = new object();
        private readonly MemoryStream buffer = new MemoryStream();
        private readonly Stream destination;
        private readonly int limit;
        private readonly bool passthrough;
        internal bool Streaming;
        internal bool Overflow;
        internal long Count;

        internal OutputCapture(Stream destination, int limit, bool passthrough)
        {
            this.destination = destination;
            this.limit = limit;
            this.passthrough = passthrough;
        }

        internal void Read(Stream source)
        {
            try
            {
                byte[] chunk = new byte[8192];
                int count;
                while ((count = source.Read(chunk, 0, chunk.Length)) > 0)
                {
                    lock (sync)
                    {
                        Count += count;
                        if (!Streaming && !Overflow && buffer.Length + count > limit)
                        {
                            Overflow = true;
                            if (passthrough) SwitchToRawLocked();
                        }
                        if (Streaming) destination.Write(chunk, 0, count);
                        else if (!Overflow) buffer.Write(chunk, 0, count);
                    }
                }
            }
            catch (IOException) { }
            catch (ObjectDisposedException) { }
        }

        private void SwitchToRawLocked()
        {
            if (Streaming) return;
            buffer.WriteTo(destination);
            destination.Flush();
            Streaming = true;
        }

        internal void SwitchToRaw()
        {
            lock (sync) SwitchToRawLocked();
        }

        internal byte[] Bytes()
        {
            lock (sync) return buffer.ToArray();
        }
    }

    private static Thread Background(ThreadStart action)
    {
        Thread thread = new Thread(action);
        thread.IsBackground = true;
        thread.Start();
        return thread;
    }

    private static bool Eligible(string[] args)
    {
        if (String.IsNullOrEmpty(Environment.GetEnvironmentVariable("CODEX_THREAD_ID")) &&
            String.IsNullOrEmpty(Environment.GetEnvironmentVariable("CODEX_SESSION_ID"))) return false;
        if (Environment.GetEnvironmentVariable("HEADROOM_COMMAND_ACTIVE") == "1" ||
            Environment.GetEnvironmentVariable("HEADROOM_EXACT") == "1" ||
            !Console.IsOutputRedirected || args.Length == 0) return false;
        string tool = args[0].ToLowerInvariant();
        string subcommand = args.Length > 1 ? args[1].ToLowerInvariant() : "";
        bool supported = tool == "rg" || tool == "grep" || tool == "pytest" ||
            (tool == "git" && (subcommand == "status" || subcommand == "log")) ||
            (tool == "cargo" && (subcommand == "build" || subcommand == "test" || subcommand == "check" || subcommand == "clippy")) ||
            (tool == "dotnet" && (subcommand == "build" || subcommand == "test"));
        if (!supported) return false;
        foreach (string argument in args)
        {
            string value = argument.ToLowerInvariant();
            if (value == "--json" || value.StartsWith("--json=") || value == "--format" ||
                value.StartsWith("--format=") || value == "--output-format" ||
                value.StartsWith("--output-format=") || value == "--message-format" ||
                value.StartsWith("--message-format=") || value == "--porcelain" ||
                value.StartsWith("--porcelain=") || value == "--raw" || value == "--numstat" ||
                value == "--name-only" || value == "--name-status" || value == "-z" ||
                value == "--null" || value == "--null-data" || value == "--patch" ||
                value == "-p" || value == "--patch-with-stat" || value == "--cc" || value == "-c" ||
                value == "-u" || value.StartsWith("-u") || value.StartsWith("-l") && tool == "git" ||
                value == "--pretty" || value.StartsWith("--pretty=") ||
                value == "--files" || value == "--files-with-matches" || value == "--files-without-match" ||
                value == "--count" || value == "--count-matches" || value == "--vimgrep" ||
                value == "--replace" || value.StartsWith("--replace=") || value == "--only-matching" ||
                value == "-l" || value == "-o" || value == "-r" ||
                value == "--help" || value == "-h" || value == "--version" ||
                value == "--watch" || value == "--interactive") return false;
        }
        return true;
    }

    private static byte[] Worker(string root, string mode, byte[] input, int timeout)
    {
        string python = Path.Combine(root, "headroom", ".venv", "Scripts", "python.exe");
        string script = Path.Combine(root, "headroom_run.py");
        if (!File.Exists(python) || !File.Exists(script)) return null;
        try
        {
            var start = new ProcessStartInfo(python, "-u " + QuoteArgument(script) + " " + mode);
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WorkingDirectory = root;
            start.RedirectStandardInput = true;
            start.RedirectStandardOutput = true;
            start.RedirectStandardError = true;
            start.EnvironmentVariables["HEADROOM_COMMAND_ACTIVE"] = "1";
            using (Process process = Process.Start(start))
            {
                if (process == null) return null;
                var captured = new OutputCapture(Stream.Null, 4 * 1024 * 1024, false);
                Thread reader = Background(delegate { captured.Read(process.StandardOutput.BaseStream); });
                Thread errors = Background(delegate {
                    try { process.StandardError.BaseStream.CopyTo(Stream.Null); }
                    catch (IOException) { } catch (ObjectDisposedException) { }
                });
                Thread writer = Background(delegate {
                    try {
                        process.StandardInput.BaseStream.Write(input, 0, input.Length);
                        // Close the byte stream directly: disposing the unused
                        // StreamWriter can append an encoding preamble.
                        process.StandardInput.BaseStream.Close();
                    } catch (IOException) { } catch (ObjectDisposedException) { }
                });
                if (!process.WaitForExit(timeout))
                {
                    // The bundled offline worker starts no subprocesses.
                    // Only this newly created worker is terminated, never RTK.
                    try { process.Kill(); process.WaitForExit(1000); } catch { }
                    reader.Join(250); errors.Join(250); writer.Join(250);
                    return null;
                }
                bool drained = reader.Join(500);
                errors.Join(250); writer.Join(250);
                return process.ExitCode == 0 && drained && !captured.Overflow ? captured.Bytes() : null;
            }
        }
        catch { return null; }
    }

    private static byte[] Filter(string root, byte[] original, out Dictionary<string, object> receipt)
    {
        receipt = Status(original.Length < MinOutputBytes ? "small_output" : "compression_unavailable");
        if (original.Length < MinOutputBytes) return original;
        try
        {
            // The .NET Framework pipe writer may emit an encoding preamble.
            // A JSON/base64 envelope keeps that transport prefix distinct from
            // an actual BOM or arbitrary bytes in the original command output.
            byte[] packet = Encoding.UTF8.GetBytes("{\"input\":\"" + Convert.ToBase64String(original) + "\"}");
            byte[] response = Worker(root, "--filter-packet", packet, 8000);
            if (response == null) return original;
            var serializer = new JavaScriptSerializer();
            serializer.MaxJsonLength = 4 * 1024 * 1024;
            var result = serializer.Deserialize<Dictionary<string, object>>(Encoding.UTF8.GetString(response));
            if (result == null || !result.ContainsKey("status") ||
                !result.ContainsKey("output")) return original;
            byte[] output = Convert.FromBase64String((string)result["output"]);
            string status = result["status"] as string;
            if (status == "compressed")
            {
                if (output.Length == 0 || output.Length >= original.Length ||
                    !result.ContainsKey("input_tokens") || !result.ContainsKey("output_tokens") ||
                    Convert.ToInt64(result["input_tokens"]) <= Convert.ToInt64(result["output_tokens"])) return original;
            }
            else
            {
                if (output.Length != original.Length) return original;
                for (int i = 0; i < original.Length; i++) if (output[i] != original[i]) return original;
            }
            // The candidate stays private until validated and written.
            result.Remove("output");
            receipt = result;
            return output;
        }
        catch { return original; }
    }

    private static Dictionary<string, object> Status(string status)
    {
        return new Dictionary<string, object> {
            {"status", status}, {"input_tokens", null}, {"output_tokens", null}, {"content_hash", null}
        };
    }

    private static void Record(string root, Dictionary<string, object> receipt, int exitCode, long stdoutBytes)
    {
        if (receipt == null) return;
        var record = new Dictionary<string, object> {
            {"result", receipt}, {"executable", "rtk.exe"},
            {"return_code", exitCode}, {"stdout_bytes", stdoutBytes},
            // Stderr remains inherited and is not inspected by this launcher.
            {"stderr_bytes", 0}
        };
        Worker(root, "--record-result", Encoding.UTF8.GetBytes(new JavaScriptSerializer().Serialize(record)), 2000);
    }
    // ProcessStartInfo.ArgumentList is unavailable on the installed .NET
    // Framework. Encode each argument using the Windows CRT quoting rules.
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

    private static bool InformationOnly(string[] args)
    {
        return args.Length == 0 || Array.IndexOf(new[] {
            "gain", "help", "--help", "-h", "--version", "-V", "recall", "verify"
        }, args[0]) >= 0;
    }

    private static int LayaWorker(string root, string value, bool authorize)
    {
        string python = Path.Combine(root, "headroom", ".venv", "Scripts", "python.exe");
        string script = Path.Combine(root, "laya_dispatch.py");
        if (!File.Exists(python) || !File.Exists(script))
        {
            if (authorize) Console.Error.WriteLine("Codex Token Saver: Laya authorization is unavailable.");
            return 78;
        }
        string mode = authorize ? " --authorize rtk " : " --record-rtk ";
        var start = new ProcessStartInfo(python, QuoteArgument(script) + mode + QuoteArgument(value));
        start.UseShellExecute = false;
        start.CreateNoWindow = true;
        start.WorkingDirectory = root;
        start.RedirectStandardInput = true;
        start.RedirectStandardOutput = true;
        start.RedirectStandardError = !authorize;
        // Authorization is an external request; marking it internal would make
        // the Python gateway bypass its own toggle and routing checks.
        if (!authorize) start.EnvironmentVariables["CTS_LAYA_INTERNAL"] = "1";
        using (Process process = Process.Start(start))
        {
            if (process == null) return 78;
            // Authorization must neither consume native stdin nor pollute stdout.
            process.StandardInput.BaseStream.Close();
            var discarded = new OutputCapture(Stream.Null, 0, true);
            Thread reader = Background(delegate { discarded.Read(process.StandardOutput.BaseStream); });
            Thread errors = authorize ? null : Background(delegate { discarded.Read(process.StandardError.BaseStream); });
            if (!process.WaitForExit(authorize ? 10000 : 2000))
            {
                try { process.Kill(); process.WaitForExit(1000); } catch { }
                reader.Join(250);
                if (errors != null) errors.Join(250);
                if (authorize) Console.Error.WriteLine("Codex Token Saver: Laya authorization timed out.");
                return 124;
            }
            reader.Join(500);
            if (errors != null) errors.Join(250);
            if (authorize && process.ExitCode != 0) Console.Error.WriteLine("Codex Token Saver: Laya authorization denied RTK.");
            return process.ExitCode;
        }
    }

    private static int Completed(string root, string[] args, int exitCode)
    {
        // Only an executed command earns a completion record. Bookkeeping is
        // best effort, never a retry, and receives no command arguments/content.
        if (!InformationOnly(args) && Environment.GetEnvironmentVariable("CTS_LAYA_INTERNAL") != "1")
        {
            try { LayaWorker(root, exitCode.ToString(System.Globalization.CultureInfo.InvariantCulture), false); }
            catch { }
        }
        return exitCode;
    }

    private static int Main(string[] args)
    {
        try
        {
            string root = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ".."));
            string executable = Path.Combine(root, "tools", "rtk.exe");
            if (!File.Exists(executable))
            {
                Console.Error.WriteLine("Codex Token Saver: RTK executable is missing: " + executable);
                return 127;
            }
            bool automatic = args.Length > 0 && args[0] == "--cts-automatic";
            if (automatic)
            {
                var originalArgs = new string[args.Length - 1];
                Array.Copy(args, 1, originalArgs, 0, originalArgs.Length);
                args = originalArgs;
            }
            var preferences = Preferences(root);
            string[] selectedArgs;
            try { selectedArgs = preferences["rtk"] ? args : WithoutRtkCompression(args); }
            catch (ArgumentException error) { Console.Error.WriteLine(error.Message); return 64; }
            if (preferences["rtk"] && !automatic && !InformationOnly(args) &&
                Environment.GetEnvironmentVariable("HEADROOM_COMMAND_ACTIVE") != "1" &&
                Environment.GetEnvironmentVariable("CTS_LAYA_INTERNAL") != "1")
            {
                int authorization = LayaWorker(root, args[0], true);
                if (authorization != 0) return authorization;
            }
            var arguments = new StringBuilder();
            foreach (string argument in selectedArgs)
            {
                if (arguments.Length > 0)
                    arguments.Append(' ');
                arguments.Append(QuoteArgument(argument));
            }

            var start = new ProcessStartInfo(executable, arguments.ToString());
            start.UseShellExecute = false;
            // Stdin and stderr remain inherited. Eligible Codex stdout has a
            // bounded capture window; every other invocation stays unchanged.
            start.EnvironmentVariables["RTK_DB_PATH"] = Path.Combine(root, "data", "rtk", "history.db");
            bool captureOutput = preferences["headroom_local"] && Eligible(args);
            start.RedirectStandardOutput = captureOutput;
            using (Process process = Process.Start(start))
            {
                if (process == null)
                    throw new InvalidOperationException("Windows did not start RTK.");
                if (!captureOutput)
                {
                    process.WaitForExit();
                    return Completed(root, args, process.ExitCode);
                }
                Stream stdout = Console.OpenStandardOutput();
                var capture = new OutputCapture(stdout, MaxOutputBytes, true);
                Thread reader = Background(delegate { capture.Read(process.StandardOutput.BaseStream); });
                if (!process.WaitForExit(5000))
                {
                    capture.SwitchToRaw();
                    process.WaitForExit();
                }
                if (!reader.Join(5000))
                {
                    capture.SwitchToRaw();
                    process.StandardOutput.Close();
                    reader.Join(250);
                }
                if (!capture.Streaming)
                {
                    byte[] original = capture.Bytes();
                    Dictionary<string, object> receipt = Status("command_failed");
                    byte[] selected = process.ExitCode == 0 ? Filter(root, original, out receipt) : original;
                    stdout.Write(selected, 0, selected.Length);
                    stdout.Flush();
                    if (receipt != null)
                    {
                        // Bookkeeping follows successful delivery. Failure may
                        // undercount savings but can never claim undelivered text.
                        Record(root, receipt, process.ExitCode, original.Length);
                    }
                }
                else
                {
                    stdout.Flush();
                    Record(root, Status(capture.Overflow ? "size_limit" : "streaming_timeout"), process.ExitCode, capture.Count);
                }
                return Completed(root, args, process.ExitCode);
            }
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine("Codex Token Saver: could not start RTK: " + exception.Message);
            return 1;
        }
    }
}
