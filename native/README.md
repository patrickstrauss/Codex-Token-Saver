# Native RTK launcher

`bin/rtk.exe` launches the unchanged upstream binary `tools/rtk.exe`, assigns the
stable bundle's `data/rtk/history.db` to the child process, and returns its exit
code. It preserves the current directory and inherits stdin, stdout, and stderr.
No command shell interprets the arguments between this launcher and RTK.

Build with Windows PowerShell:

```powershell
& "$env:USERPROFILE\CodexTokenSaver\native\Build-RtkLauncher.ps1"
```

Run the integration tests with the bundle's Python:

```powershell
& "$env:USERPROFILE\CodexTokenSaver\dashboard\.venv\Scripts\python.exe" -m unittest discover -s "$env:USERPROFILE\CodexTokenSaver\tests" -p test_rtk_launcher.py -v
```

The tests compile a fake downstream tool inside an isolated temporary bundle.
They check metacharacters, spaces, empty arguments, embedded quotes, backslashes,
Thai text, streams, working directory, database location, and exit codes.

`rtk.cmd` remains for legacy callers, but `rtk` resolves to the native executable
when Windows uses its normal `.EXE`-before-`.CMD` extension order. Explicitly
calling `rtk.exe` is preferred, because a `.cmd` caller has already subjected its
arguments to command-shell parsing before our code can receive them.
