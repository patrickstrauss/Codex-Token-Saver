# Release acceptance

Every release must link a successful Windows package workflow for the exact commit
and preserve its ZIP checksum, benchmark JSON, runtime inventory and test results.
CI is a prerequisite, not a substitute for a human clean-desktop test.

- [ ] Owner approves the root license, third-party notices and public visibility.
- [ ] Scan the full Git history and release contents for credentials/private data.
- [ ] Clean Windows CI: full install and CoreOnly install; no developer Python/Node required by installer.
- [ ] Invalid manifest/checksum, traversal, duplicate-case path and local source edits refuse safely.
- [ ] Same-release rerun, missing artifact repair and isolated Codex config/auth preservation pass.
- [ ] Source upgrade succeeds; injected validation failure restores added/removed/changed source.
- [ ] Guided uninstall leaves native Codex configuration usable and unrelated integrations/data intact.
- [ ] Clean Windows 11 x64 standard-user VM: download/extract/install, trust hook, open tray/dashboard and use tools.
- [ ] VM reboot/login: singleton tray/dashboard/proxy ownership, normal native Codex connectivity.
- [ ] VM uninstall while active asks for close/restart; after restart it completes and native Codex resumes.
- [ ] VM reinstall succeeds; backup is retained; uninstall/refusal paths preserve unrelated tasks/shortcuts.
- [ ] Benchmark facts/recovery pass, overhead/expansion reported, no model/quota claims inferred.
- [ ] Draft release contains ZIP, checksum, limitations and exact test evidence. Owner reviews before publication.

Current public support target is Windows 11 x64. CI uses Windows Server images;
Windows 10, ARM64, macOS and Linux are not qualified. A skipped or unperformed gate
must remain unchecked. Until desktop/reboot qualification passes, label a release
**preview**, not stable or “fully tested.” Code signing is not implemented.
