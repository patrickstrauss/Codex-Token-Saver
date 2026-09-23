# Install Codex Token Saver for your team

Use **Windows 10/11 x64**, an ordinary user account, and an installed Codex desktop app. Sign into Codex normally before installing. No administrator account, Git, Python, or developer tools are required. Windows .NET Framework 4.x must be available. Internet access to GitHub, PyPI and OpenAI's tokenizer host is required for the first installation. Leave several GB free for Python libraries and download caches; GGUF models need additional space.

## Download the workflow artifact

1. Sign into GitHub with an account that has access to [Codex-Token-Saver](https://github.com/patrickstrauss/Codex-Token-Saver). This repository is private. If you see a 404 or cannot download artifacts, ask the repository owner for access or for the checked ZIP and checksum.
2. Open the repository's [Actions tab](https://github.com/patrickstrauss/Codex-Token-Saver/actions). Open the **Windows package** run approved by your maintainer. Confirm its green **Success** result and the expected branch/commit. Do not use a failed or still-running build.
3. On that run's summary page, find **Artifacts** and click **windows-package**. This downloads GitHub's outer artifact ZIP, usually named `windows-package.zip`.
4. In Windows Explorer, right-click that download and choose **Extract All**. Inside are an installer ZIP named `Codex-Token-Saver-<version>-windows-x64.zip` and its matching `.zip.sha256` file.
5. Verify the **inner installer ZIP** against the checksum. Open PowerShell in the extracted artifact folder and run the following, replacing `ci-3` with the version you downloaded:

   ```powershell
   Get-FileHash -Algorithm SHA256 -LiteralPath '.\Codex-Token-Saver-ci-3-windows-x64.zip'
   Get-Content -LiteralPath '.\Codex-Token-Saver-ci-3-windows-x64.zip.sha256'
   ```

   The hash must match the first value in the checksum file; upper/lowercase does not matter. If it differs, stop and obtain a fresh artifact.
6. Right-click the **inner installer ZIP** and choose **Extract All** again. Open its extracted `Codex-Token-Saver-<version>-windows-x64` folder. Keep these items together:

   ```text
   Install.cmd
   Install.ps1
   Repair-Team-Setup.cmd
   Setup-Request-Compression.cmd
   Disable-Token-Saver.cmd
   Get-Token-Saver-Diagnostics.cmd
   package-manifest.json
   payload\
   ```

**Do not use GitHub's Code → Download ZIP** for installation: that contains repository source, not the built installer. Do not launch `Install.cmd` inside a ZIP preview, or copy it away from its manifest and payload.

The [verified September 20 build](https://github.com/patrickstrauss/Codex-Token-Saver/actions/runs/35514551689) is a known-good preview example. Its artifact expires October 4, 2026; use a newer maintainer-approved successful run when available. Workflow artifacts are retained for **14 days**. If an artifact has expired, ask the maintainer to generate a fresh build. New guide changes are included in subsequent successful builds; already-downloaded ZIPs do not update themselves.

## Install and open the dashboard

1. Save your work and close Codex before installation so it can load the new tools when reopened. Keep your normal Codex sign-in; no API key is required by this installer.
2. Double-click the extracted **Install.cmd**. Leave its window open while downloads and checks run. It installs into `%USERPROFILE%\CodexTokenSaver`, registers the local file tools and optional command hook, adds the user's PATH entry, and installs a Start menu shortcut and logon scheduled task. No administrator elevation is requested.
3. Wait for **Installed and checked** and the instruction to restart Codex. If the window says **Installation stopped**, follow the error rather than treating the installation as complete. Press a key to close the finished installer.
4. Open **Codex Token Saver** from the Windows Start menu. Installation registers startup; it does not itself open the tray app. Open the [dashboard](http://127.0.0.1:8095/) or click the **TS** tray icon. The icon may be under the tray's up-arrow.
5. Configure the controls below, then reopen Codex. Its existing connection, model, reasoning, authentication, approval settings and task history are preserved. New tasks and resumed tasks can use tools after Codex loads them; verify activity rather than relying only on a **Configured** label.
6. For automatic RTK command routing, open **Codex Settings → Hooks → Reload hooks → User**, review **Checking automatic Headroom command compression**, and click **Trust**. This existing shared hook name covers RTK and local Headroom. The installer registers the definition but never grants trust. If hooks were explicitly disabled in your Codex configuration, that choice is preserved and automatic routing stays unavailable.

## Set up the team defaults

In the dashboard's **Your toolkit** section, use these controls. Each row also names its underlying library.

| Dashboard control | Team setting | What to expect |
| --- | --- | --- |
| Command output — RTK | **On** (installed default) | Reduces explicit RTK calls; the trusted hook also routes eligible bare Git/search commands automatically. |
| Local file & output reading — Headroom | **On** (installed default) | Local file tools and eligible RTK output compression; activity can legitimately produce zero reduction. |
| Code navigation — Serena | Turn **On** | Registers the symbol tools and coding guidance. Reopen Codex afterward so it loads them. |
| Request compression — Headroom | **Off** until local setup passes | Run **Setup-Request-Compression.cmd**, then turn it On in the dashboard if desired. See below. |
| Task summaries — LangMem | Leave **Off** | Local-summary work is paused; generating a summary does not reduce the existing Codex task's context. |
| Local model — llama.cpp | Leave **Off** | llama.cpp is not required by RTK, local file tools or Serena. |

Serena is preferred implicitly for relevant coding navigation; team members do not need to request it in every prompt. It does not intercept all activity. It retrieves symbols, exact bodies and references when useful, with native file tools as a fallback. See [Test Serena in Codex](SERENA-TESTING.md) for a repeatable test and an ordinary coding prompt.

## Check that setup worked

- Confirm the dashboard opens and reports the expected On/Off settings. **Configured** means registration exists, not proof that a task has used the tool.
- In a new PowerShell window, check the installed RTK launcher:

  ```powershell
  & "$env:USERPROFILE\CodexTokenSaver\bin\rtk.exe" --version
  ```

  The initial bundle reports `rtk 0.49.0`. This checks the executable, not token savings. Use a supported command in your normal coding work to produce real activity.
- After enabling Serena and reopening Codex, open or resume a task in your own code project and ask: **“Identify this project's main entry points and relevant symbols. Do not edit files.”** Check for Serena tool calls and an updated **Code navigation** activity count. The [full Serena check](SERENA-TESTING.md) verifies bodies, references, project switching and disabling against isolated fixtures.
- After trusting the hook, a single ordinary `git status --short`, `git diff`, `git log -5 --oneline` or `rg` display call in a Windows project can use RTK even if the task omits its prefix. Scripts, pipelines, dynamic arguments, machine output and WSL/POSIX paths deliberately stay native. Use `# rtk: exact` or `# headroom: exact` on a native call when completeness matters. RTK usage can increase with zero savings for small outputs; the dashboard itself does not execute commands.
- At the next Windows login, check that the tray/dashboard starts. A successful installation test is not a substitute for a login test on your teammate's laptop.

These controls work in existing coding tasks once their tools are loaded; no new conversation is required just to use RTK or Serena. Restarting Codex is for changed tool registration/configuration, not a routine per-command requirement. Activity and local token-reduction estimates are not measured weekly-quota savings.

## Included libraries and deferred features

Default installation includes Headroom 0.37.0, RTK 0.49.0, Serena 1.7.0, LangMem 0.0.30 and llama.cpp b10809 (CPU). New Python environments use 3.13.14. Serena, local summaries and local inference initially stay **off**; enable the desired controls in the dashboard. Follow [the Serena check](SERENA-TESTING.md) to verify navigation against your project.

Local summaries are paused for the current team setup. If the team explicitly revisits that experiment later, **Select-Local-Model.cmd** inside the installed folder selects a compatible GGUF model you already have; **Task summaries** and **Local model** then allow an explicitly selected task to be summarized. No GGUF is downloaded or loaded by installation or selection. The CPU build needs no GPU driver but may be slow, and selecting a file does not prove model compatibility. Summaries remain separate, lossy reference files and do not replace native Codex compaction or the current conversation. There is no need to select a model for the recommended setup above.

## Optional request compression

1. Finish the normal installation first. Double-click **Setup-Request-Compression.cmd** in the extracted deployment package or installed folder. It downloads and verifies the public compression model; the first download can take up to 15 minutes and requires access to Hugging Face as well as GitHub. This model is separate from the optional GGUF summary model.
2. Leave the window open until setup succeeds. Setup checks the installed runtime, compression, exact original-content retrieval and a backend on an isolated local port. It records validation for this machine and starts the managed connection in its paused state. Codex keeps its current connection throughout setup; no API key or paid model request is needed for validation.
3. Refresh the dashboard and turn **Request compression** On. This warms the backend before the existing controller changes routing. Restart Codex once after enabling, then resume existing tasks. Check observed request activity rather than expecting every request to shrink.

Setup preserves an already validated, enabled connection. A failure does not enable routing; keep the error text and retry after addressing it. Setup rolls back its proxy metadata and stops a supervisor it newly created when a later step fails. Shared Windows PATH/Start menu maintenance is not a full system transaction. Port conflicts preserve the existing service instead of stopping it. Use **Pause** in the dashboard or `Restore-Codex-Direct.ps1` for recovery; restart Codex after a routing change.

Do not copy another person's validation receipts or run the historical `activate_validated_request_proxy.py` script. The normal installer never silently enables request compression. Local summaries and llama.cpp can stay Off while request compression is used.

## Repair an earlier team installation

Download and fully extract the latest approved deployment artifact. Run its **Repair-Team-Setup.cmd**, leaving the existing `%USERPROFILE%\CodexTokenSaver` folder in place. This corrects the dashboard's RTK history/executable paths, checks RTK's history schema without fabricating command records, and repairs the local-tool and hook status receipts. It preserves component choices, existing history, Codex model/reasoning/authentication settings and routing. Configuration backups are saved under `backups\team-repair-*`.

Restart the dashboard from the tray's **Restart / repair dashboard** item, reopen Codex, then review/trust its shared command hook if requested. A new installation with no recorded commands should show zero activity, not an unreadable-history error. Explicit process environment overrides can supersede `dashboard\.env`; the repair report lists conflicting override names for review.

This targeted repair supports installations made by the team installer; it does not replace all installed source files or libraries. Do not use **Install.cmd** from a different release to overwrite an older installation. The new artifact's **Setup-Request-Compression.cmd** can also prepare request compression against an existing team installation, validating that machine's installed proxy code before activation.

## Troubleshooting, updates and removal

For high process counts, collect **Get-Token-Saver-Diagnostics.cmd** before deleting anything. To disable the bundle, fully quit Codex, run **Disable-Token-Saver.cmd**, then restart Windows after it succeeds. This leaves files/history in place. See [process recovery](PROCESS-RECOVERY.md), including steps when the installation folder was already deleted.

| Symptom | Next step |
| --- | --- |
| GitHub 404, no artifact, or expired download | Confirm repository access, a successful approved run, and artifact retention. Ask the maintainer for a fresh checked build when needed. |
| Missing `payload` or `package-manifest.json` | Extract both ZIP layers fully and run the launcher beside those items. |
| Download/dependency setup failed | Keep the error window or its text, fix the connection/permission issue, then rerun the **same** installer. Do not delete the installation folder to retry. |
| Existing installation/different release refused | Stop and ask the maintainer to perform a reviewed source upgrade. Do not overwrite the folder or its state manually. |
| Dashboard does not open | Open **Codex Token Saver** from Start. If needed, run `Start-Services.ps1` from `%USERPROFILE%\CodexTokenSaver` and inspect its `logs` folder. |
| Serena is On but tools are absent | Reopen Codex after enabling it, check the dashboard's availability explanation, then follow the Serena test. Do not copy another user's Codex config. |
| Savings stay at zero | Confirm the tool was actually used on eligible content. Version checks, small output and exact reads can produce no savings. |
| Bare Git/search calls never use RTK | Check the RTK toggle, trust the shared command hook, and restart Codex once after installation so it inherits the bundle PATH. Complex/exact commands stay native. |
| RTK shows Error before first use, or tray says local Headroom is not configured | Run **Repair-Team-Setup.cmd** from the latest extracted artifact, then restart the dashboard. |
| Request compression is unavailable | Run **Setup-Request-Compression.cmd**, wait for successful local validation, then enable it in the dashboard. |

Rerun the same **Install.cmd** after a failed download. Verified downloads are cached. Completed environments are preserved, and source checksums are checked before resuming. The same source release may add the optional runtimes after a core-only installation. Library updates and rollbacks use the dashboard's existing controls.

The installer deliberately refuses an existing nonempty legacy folder, a different source release, or locally modified source. It does not overwrite working runtimes or local state. Source upgrades currently require the maintainer's reviewed backup/deployment process; there is no automatic source updater or one-click uninstaller yet. Keep the old installation and its backups until the replacement has been checked. Do not delete the folder while startup entries or Codex MCP entries still point to it.

Configuration backups are under the installed `backups` directory; startup registration writes `install-startup-result.json`. Successful setup writes `team-install-result.json`. Download or dependency failures happen before Codex registration. Tools, guidance and hook registration roll back together if a write fails, unless another writer changed a file in the meantime. Existing unrelated hooks and trust are preserved; a different existing bundle hook is refused for review. A startup failure may occur after local tools were registered; rerunning retries startup. Unrelated settings are preserved, and the original configuration backup remains available. Settings and authentication files are never included in release packages.

The ZIP and native launchers are currently **unsigned**. Windows SmartScreen or organizational policy may require IT approval. Check the source and release checksum; do not disable organization security policies. The process-level PowerShell execution-policy override in the launcher does not change machine policy. First installation is **not offline**; this ZIP is not an air-gapped installer. Checksum verification protects pinned downloads, but a checksum shipped beside an untrusted ZIP is not a publisher signature.

## Maintainer checks and private releases

From the repository, on Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\Build-Package.ps1 -Version 0.1.0
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\Smoke-Package.ps1 -PackageDirectory .scratch\packages\Codex-Token-Saver-0.1.0-windows-x64
```

The smoke test installs into a new temporary directory, uses a synthetic Codex profile, checks real library imports and local compression, and verifies repeated installation and settings preservation. Its offline benchmark also requires important facts and exact originals to survive the test fixtures before an artifact is published. See [performance checks](PERFORMANCE-CHECK.md) for scope, latency reporting and optional matched-task comparisons. It does not register startup or touch the maintainer's live bundle. Add `-CoreOnly` for the smaller Headroom/RTK/dashboard check. The temporary directory is retained as evidence; delete that specific directory after review.

`Install.ps1 -Plan` verifies package files and prints the proposed destination without writing. `Install.ps1 -CoreOnly` omits optional libraries; `-SkipIntegration -InstallDirectory <empty-directory>` is for isolated tests and skips PATH, shortcuts, startup and real Codex registration.

The **Windows package** GitHub workflow compiles the existing native launchers, runs a fresh full installation and settings-preservation check, and uploads the ZIP and checksum as a private repository artifact. A `v*` tag or manual run with **draft_release** enabled creates a **draft** release after checks pass. Manual releases require a tag. Review and publish that draft explicitly; the workflow never changes repository visibility. A private repository's releases remain private.

Pull requests trigger preview builds automatically. Pushes to `main`/`master` and `v*` tags also trigger the workflow. Once the workflow exists on the repository's default branch, a maintainer can open **Actions → Windows package → Run workflow**, choose the reviewed branch/ref, and leave **draft_release** unchecked for an artifact-only build. Before default-branch integration, use the pull request's successful check/run link. Share the exact successful run with the team; do not describe a merely queued run as a checked installer. For a durable download, review and publish a release instead of relying on a 14-day artifact. Team members still need private repository access unless the owner distributes the checked ZIP and checksum separately.

Dependencies are pinned in `packaging/dependencies.json` and hashed `requirements-*.txt`. The Python archive checksum comes from the pinned uv release's embedded manifest. Requirements were resolved against the tested installation's package versions; `.in` files record direct requirements. No installed virtual environment is copied. To update locks, resolve deliberately, review the change, then run the complete smoke test before releasing.

Upstream distribution references: [uv](https://docs.astral.sh/uv/), [Python management](https://docs.astral.sh/uv/concepts/python-versions/), [RTK releases](https://github.com/rtk-ai/rtk/releases), [Headroom](https://pypi.org/project/headroom-ai/0.37.0/), [Serena](https://pypi.org/project/serena-agent/1.7.0/), [LangMem](https://pypi.org/project/langmem/0.0.30/), and [llama.cpp b10809](https://github.com/ggml-org/llama.cpp/releases/tag/b10809). Dependencies retain their upstream licenses inside their installed distributions.
