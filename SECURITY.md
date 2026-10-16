# Security and privacy

Report vulnerabilities privately using this repository's GitHub **Security →
Report a vulnerability**, when enabled. Do not post credentials, personal file
contents, chat history or full diagnostics in a public issue. If private reporting
is unavailable, open an issue requesting a private contact without exploit details.
Only the latest published release is supported.

The dashboard and proxy bind to loopback. Never expose their ports through a
public interface, tunnel or port forward. The proxy handles authenticated model
traffic locally; it must be trusted like the Codex client itself. The bundle does
not provide an account or collect your account credentials for reporting.

File compression stores original text locally for exact retrieval. Caches and
logs can contain sensitive source files, command output, repository paths and
task identifiers. Runtime/model downloads contact upstream services. Request
traffic still goes to your configured model provider. “Local compression” does
not mean Codex model inference runs locally.

Download only release assets from this repository. Compare the ZIP's SHA-256
with its accompanying checksum before extraction. Checksums detect corruption;
they do not provide publisher identity or Windows code signing. Windows may warn
about unsigned scripts and executables. Do not disable antivirus or system-wide
execution policy to install this app.

Updates verify pinned download hashes, stage runtime changes and validate
compatibility. App source updates refuse local modifications. Uninstall restores
only owned integrations and preserves data in a local backup. Delete that backup
yourself only after checking that you no longer need its private contents.
