# Install, update and uninstall

## Requirements

Windows x64, Windows PowerShell 5.1 or newer, a coding client,
and network access to GitHub, PyPI, npm, Python/Node download servers and Hugging
Face. Administrator access, a global Python/Node install and OpenCodex are not
required. Full installation includes a CPU routing model and several isolated
Python environments; download size and RAM use depend on enabled components.
ARM64, macOS, Linux and multi-user machine-wide installs are not supported.
CI coverage is listed in the release checklist; do not infer Windows 10/11
qualification from a Windows Server CI run alone.

The default installer configures Codex. To use another MCP client without Codex,
run `Install.ps1 -Harness standalone`, then follow [Coding clients](CODING-CLIENTS.md).
This mode registers Windows startup and the app while leaving Codex settings
untouched. Existing Codex users can add MCP clients with `Connect-Harness.ps1`.

## Install a release

1. Download a ZIP and its `.sha256` file from [Releases](https://github.com/patrickstrauss/Codex-Token-Saver/releases).
   Until a public release is published, Actions artifacts are test builds only.
2. In PowerShell, run `Get-FileHash .\Codex-Token-Saver-VERSION-windows-x64.zip -Algorithm SHA256`
   and compare the hash to the checksum file. Fully extract the ZIP first.
3. Close Codex. Run `Install.cmd` from the extracted folder. Keep its window open
   until it reports success. If it fails, retain the error and retry the same
   release; do not move a partially created installation or run a different release
   over it. The installation is `%USERPROFILE%\CodexTokenSaver`.
4. Reopen Codex. Open **Codex Token Saver** from the Start menu and use its
   **Toolkit** controls. Optional components remain off until you enable them.
   Review/trust the command hook in Codex Settings when prompted.
5. Follow [using the bundle](USING-BUNDLE.md). Request compression requires the
   separate `Setup-Request-Compression.cmd` validation and an explicit On choice;
   normal installation preserves your provider, model and authentication.

For a smaller install, run `powershell -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -CoreOnly`.
For a no-write preview add `-Plan`. `-SkipIntegration -InstallDirectory PATH` is
for isolated test/development installs and does not register a usable Codex setup.
An installed Python venv is not portable: do not copy it between PCs or move it.

## Updates

Use **Updates** in the dashboard for supported library updates. Downloads and
compatibility checks complete before activation; retain the previous runtime for
rollback. This is separate from updating the app's source files.

For an app update, download/extract the new release and preview with
`powershell -NoProfile -ExecutionPolicy Bypass -File .\Upgrade-App.ps1 -Plan`.
Close Codex and stop bundle workers first. If workers remain, run
`Disable-Token-Saver.cmd`, restart Windows, and retry before reopening Codex.
Run `Upgrade-App.cmd` from the **new extracted release**. It verifies both
manifests, refuses local edits, backs up changed source, validates the installed
runtime and rolls back source on validation failure. User data and toggles stay
intact. Refresh the library version display by reopening the dashboard.

An app release that changes runtime pins deliberately requires a clean reinstall:
uninstall as below, retain the backup, then install the new release. Re-enable
only the desired integrations. Older developer/team installs without an ownership
manifest also require a reviewed migration; do not fabricate a manifest. Restore
only needed data/history from the backup, never old venvs, routing receipts or
authentication files. Automatic source migration across arbitrary runtime
versions is not supported.

## Uninstall

Close Codex, then choose **Codex Token Saver → Uninstall** in Windows Installed
apps, or run `Uninstall-Token-Saver.cmd` from the installed folder. Type
`UNINSTALL` to confirm. A PowerShell `-Plan` preview makes no changes.

The uninstaller validates ownership, restores the owned request route, disables
bundle tools/hooks/guidance and startup, then checks for active workers. If it
asks for a restart, restart Windows yourself and run uninstall again **before
opening Codex**. It does not kill apps or restart Windows automatically.

Once idle, it removes owned scheduled tasks, shortcuts and the Installed apps
entry, and moves the installation to a dated folder in
`%USERPROFILE%\CodexTokenSaver-Backups`. No file contents or saved histories are
discarded. After verifying native Codex works, delete that backup in Explorer to
reclaim disk space. Unrelated MCP registrations, hooks, conversations, model
choices and account authentication remain yours.

If ownership validation fails, keep the error and follow
[process recovery](PROCESS-RECOVERY.md). Never delete an installation before
restoring its owned endpoint. A broken/missing runtime requires the manual
recovery path; reinstalling over it is not a safe uninstall technique.
