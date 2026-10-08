# Reliability and performance reporting

The real-task audit confirmed that RTK, Headroom and Serena were being used. Two retrieval calls supplied `id` instead of `content_hash`; the Serena failure requested a file absent from the active project. These were not evidence of cache loss or a stopped language server.

## Changes

- Headroom retrieval tools provide canonical examples and actionable argument validation, while preserving strict schemas and exact-response protection.
- Serena records fixed failure categories, tool durations and per-tool counts without saving arguments, paths or source content. The dashboard shows the latest duration and historical failure separately from current health.
- Local Headroom's last-use display selects the newer file/command event instead of hiding a recent file read behind an older command check.
- Headroom request savings default to the last 15 minutes, with Today, 7 days and Lifetime available. Reads are bounded to a 2 MB ledger tail; partial or corrupt coverage is explicit. Signed expansion costs are retained. RTK already defaults to Today and identifies large outlier contributions.
- Both counters explicitly cover all tasks. The upstream ledgers do not reliably identify individual tasks, so the app does not invent per-task token totals. RTK command duration is labelled separately from filtering overhead.
- The packaged offline benchmark checks critical facts, exact originals, retrieval cost and paired latency medians. The Windows package smoke test runs it before publishing an artifact.
- A reproduced Windows updater race now retries brief file-sharing conflicts when replacing its status JSON, for at most 100 ms. Persistent failures still preserve the original file and surface an error.

## Resource and quality limits

Serena already defers language-server loading until project activation and cleans up its owned processes when its MCP connection ends. Each connection retains its own project state. The audit's approximately 1.8 GB covered several active connections; it did not establish an orphaned-process leak. No shared project pool or forced idle termination was introduced.

The benchmark uses synthetic fixtures and no model calls. It is a regression gate, not proof of unchanged LLM answers, end-to-end proxy latency or Codex quota savings. Full exact retrieval after an overview can have negative net savings; this is reported rather than hidden. See [the comparison protocol](PERFORMANCE-CHECK.md).

Model, reasoning, authentication, routing and component preferences are unchanged by this release. New MCP code loads after a normal Codex restart; ongoing tasks need not be interrupted to build the installer.

## Validation

- Dashboard: 271 tests passed.
- Core: 431 checks, zero failures/errors, one source-runtime probe skipped. The real Serena integration was checked separately.
- Real Serena integration: Python/TypeScript definitions, references, changed source, checkout switching, exact receipts, fallback and live component toggling passed against temporary fixtures.
- Offline Headroom/RTK benchmark: important facts preserved, exact originals identical, signed retrieval costs reported. Warm local Headroom overhead was approximately 9 ms for these small synthetic fixtures; this is not an end-to-end Codex latency claim.
- Windows updater: the reproduced sharing failure passed 60 consecutive repetitions after the fix.
- Windows source package builds locally. The deployment workflow independently validates a fresh installation and runs the benchmark before uploading its artifact.
