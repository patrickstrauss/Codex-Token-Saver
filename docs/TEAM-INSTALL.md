# Install Codex Token Saver for your team

Use **Windows 10/11 x64**, an ordinary user account, and an installed Codex desktop app. Sign into Codex normally before installing. No administrator account, Git, Python, or developer tools are required. Windows .NET Framework 4.x must be available. Internet access to GitHub, PyPI and OpenAI's tokenizer host is required for the first installation. Leave several GB free for Python libraries and download caches; GGUF models need additional space.

1. Obtain the reviewed `Codex-Token-Saver-<version>-windows-x64.zip` and matching `.sha256` from your team's private GitHub release or workflow artifact. Team members need repository access unless the owner distributes the ZIP directly.
2. Verify the ZIP with `Get-FileHash -Algorithm SHA256 <zip-path>` against the supplied checksum. Extract **all** files to a local folder. Do not run the installer inside the ZIP preview.
3. Double-click **Install.cmd**. It installs into `%USERPROFILE%\CodexTokenSaver`, downloads verified libraries, checks them, registers optional local file tools, adds the user's PATH entry, and installs the existing Start menu/logon tray integration. No elevation is requested.
4. Restart Codex. Open **Codex Token Saver** from the Start menu. RTK and local file compression are ready. Codex's existing connection, selected model, reasoning, authentication and approval settings are preserved.

Default installation includes Headroom 0.37.0, RTK 0.49.0, Serena 1.7.0, LangMem 0.0.30 and llama.cpp b10809 (CPU). New Python environments use 3.13.14. Serena, local summaries and local inference initially stay **off**; enable the desired controls in the dashboard. Follow [the Serena check](SERENA-TESTING.md) to verify navigation against your project.

To use local summaries, double-click **Select-Local-Model.cmd** inside the installed folder and select a compatible GGUF model you already have. Enable **Local summaries** and **llama.cpp** in the dashboard, then choose the task to summarize. No model is downloaded or loaded by installation or selection. The CPU build works without a GPU driver but may be slow; model compatibility and speed depend on your machine and GGUF. Selection does not prove model compatibility. Avoid replacing a model while a summary is running.

**Request compression is not yet supported for a fresh team installation. Keep that control off.** This package supports RTK, local Headroom file compression, Serena and summaries with a selected GGUF. It does not configure a request route, install a command hook, download the request model, or silently activate inference. Fresh Codex profiles remain on their normal connection. The historical `activate_validated_request_proxy.py` script requires the maintainer's old validation receipts; do not run it for a teammate or copy another person's receipts. A safe per-machine request-proxy bootstrap remains pending. Optional hooks need their existing trust/setup flow.

## Retry, update and remove

Rerun the same **Install.cmd** after a failed download. Verified downloads are cached. Completed environments are preserved, and source checksums are checked before resuming. The same source release may add the optional runtimes after a core-only installation. Library updates and rollbacks use the dashboard's existing controls.

The installer deliberately refuses an existing nonempty legacy folder, a different source release, or locally modified source. It does not overwrite working runtimes or local state. Source upgrades currently require the maintainer's reviewed backup/deployment process; there is no automatic source updater or one-click uninstaller yet. Keep the old installation and its backups until the replacement has been checked. Do not delete the folder while startup entries or Codex MCP entries still point to it.

Configuration backups are under the installed `backups` directory; startup registration writes `install-startup-result.json`. Successful setup writes `team-install-result.json`. Download or dependency failures happen before Codex registration. Registration rolls its configuration change back if writing guidance fails, unless another writer changed that file in the meantime. A startup failure may occur after local tools were registered; rerunning retries startup. Unrelated settings are preserved, and the original configuration backup remains available. Settings and authentication files are never included in release packages.

The ZIP and native launchers are currently **unsigned**. Windows SmartScreen or organizational policy may require IT approval. Check the source and release checksum; do not disable organization security policies. The process-level PowerShell execution-policy override in the launcher does not change machine policy. First installation is **not offline**; this ZIP is not an air-gapped installer. Checksum verification protects pinned downloads, but a checksum shipped beside an untrusted ZIP is not a publisher signature.

## Maintainer checks and private releases

From the repository, on Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\Build-Package.ps1 -Version 0.1.0
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\Smoke-Package.ps1 -PackageDirectory .scratch\packages\Codex-Token-Saver-0.1.0-windows-x64
```

The smoke test installs into a new temporary directory, uses a synthetic Codex profile, checks real library imports and local compression, and verifies repeated installation and settings preservation. It does not register startup or touch the maintainer's live bundle. Add `-CoreOnly` for the smaller Headroom/RTK/dashboard check. The temporary directory is retained as evidence; delete that specific directory after review.

`Install.ps1 -Plan` verifies package files and prints the proposed destination without writing. `Install.ps1 -CoreOnly` omits optional libraries; `-SkipIntegration -InstallDirectory <empty-directory>` is for isolated tests and skips PATH, shortcuts, startup and real Codex registration.

The **Windows package** GitHub workflow compiles the existing native launchers, runs a fresh full installation and settings-preservation check, and uploads the ZIP and checksum as a private repository artifact. A `v*` tag or manual run with **draft_release** enabled creates a **draft** release after checks pass. Manual releases require a tag. Review and publish that draft explicitly; the workflow never changes repository visibility. A private repository's releases remain private.

Dependencies are pinned in `packaging/dependencies.json` and hashed `requirements-*.txt`. The Python archive checksum comes from the pinned uv release's embedded manifest. Requirements were resolved against the tested installation's package versions; `.in` files record direct requirements. No installed virtual environment is copied. To update locks, resolve deliberately, review the change, then run the complete smoke test before releasing.

Upstream distribution references: [uv](https://docs.astral.sh/uv/), [Python management](https://docs.astral.sh/uv/concepts/python-versions/), [RTK releases](https://github.com/rtk-ai/rtk/releases), [Headroom](https://pypi.org/project/headroom-ai/0.37.0/), [Serena](https://pypi.org/project/serena-agent/1.7.0/), [LangMem](https://pypi.org/project/langmem/0.0.30/), and [llama.cpp b10809](https://github.com/ggml-org/llama.cpp/releases/tag/b10809). Dependencies retain their upstream licenses inside their installed distributions.
