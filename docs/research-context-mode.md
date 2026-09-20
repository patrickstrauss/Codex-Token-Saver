# Context Mode assessment

Read-only research, 2026-09-14. No installation or configuration changes.

Recommendation: **skip the full plugin for this bundle; consider only an isolated MCP-only pilot if its license is acceptable.** It overlaps existing compression and introduces routing and session-memory behavior that is outside the user's current scope. Symbol-aware or semantic code search would be more complementary.

## Verified project and license

[Context Mode](https://github.com/mksglu/context-mode) is currently version 1.0.169, inspected at [commit ba5f5df](https://github.com/mksglu/context-mode/commit/ba5f5dfd1a0cd3e8a8f812c219d50390ed0a61c8). It is **source-available under Elastic License 2.0**, rather than a permissively licensed open-source dependency. Its license restricts providing substantial functionality as a hosted/managed service. Do not label it MIT/Apache or assume unrestricted redistribution. Sources: [package metadata](https://github.com/mksglu/context-mode/blob/ba5f5dfd1a0cd3e8a8f812c219d50390ed0a61c8/package.json), [license](https://github.com/mksglu/context-mode/blob/ba5f5dfd1a0cd3e8a8f812c219d50390ed0a61c8/LICENSE).

## Codex and Windows

The current project supports Codex CLI through MCP plus plugin hooks; it is no longer Claude-only. Setup requires hooks/plugin_hooks feature flags, explicit hook trust, and Node on the launching process's PATH. MCP installation alone does not prove routing works. Windows-specific process/version handling and Windows hook tests exist. The documentation does not establish a separately tested Codex Desktop integration. Sources: [Codex installation](https://github.com/mksglu/context-mode#codex-cli), [Codex hooks](https://github.com/mksglu/context-mode/blob/ba5f5dfd1a0cd3e8a8f812c219d50390ed0a61c8/src/adapters/codex/hooks.ts), [Windows tests](https://github.com/mksglu/context-mode/blob/ba5f5dfd1a0cd3e8a8f812c219d50390ed0a61c8/tests/hooks/windows-hooks-normalization.test.ts).

There is a concrete blocker on this laptop: the bundled Desktop executable reports **0.154.0-alpha.6.2**, but `codex --version` through `C:\Tools\CodexShim\codex.cmd` reports **0.117.0**. Context Mode checks that PATH command and requires at least 0.141.0 for command rewriting. Below that version it converts redirections into denials. An unchanged full-plugin installation could therefore block operations instead of transparently rerouting them. Node v24.14.1 meets its >=22.5 requirement. No shim changes were made. Source: [capability detection](https://github.com/mksglu/context-mode/blob/ba5f5dfd1a0cd3e8a8f812c219d50390ed0a61c8/hooks/core/codex-caps.mjs).

## Coverage and savings

Its principal useful mechanism is executing/filtering data outside the model context, indexing larger content in SQLite FTS5, and returning selected results. MCP-only use is opt-in. Hooks add command redirects/denials and periodic guidance for external MCP tools; the adapter states that Codex does not support replacing MCP output through PostToolUse. This is not a transparent compressor for every Codex request. Coverage of nested Desktop code-mode calls needs a live pilot; source inspection alone does not establish it. Sources: [routing implementation](https://github.com/mksglu/context-mode/blob/ba5f5dfd1a0cd3e8a8f812c219d50390ed0a61c8/hooks/core/routing.mjs), [Codex adapter](https://github.com/mksglu/context-mode/blob/ba5f5dfd1a0cd3e8a8f812c219d50390ed0a61c8/src/adapters/codex/index.ts).

The advertised roughly 98% reduction compares selected raw tool-output bytes with processed/context-returned bytes. The published fixtures come from Claude Code tools and selected development tasks. This is a project benchmark, not independently verified end-to-end Codex token or bill savings. Filtering a large dataset to an answer naturally omits most data; do not add these ratios to Headroom or RTK savings. Source: [benchmark methodology and fixtures](https://github.com/mksglu/context-mode/blob/ba5f5dfd1a0cd3e8a8f812c219d50390ed0a61c8/BENCHMARK.md).

Search returns ranked chunks/snippets, with result limits and throttling; it is not proof of complete or byte-identical original recovery. The README describes a default 24-hour fetch cache and cleanup of older sources/databases after 14 days. Exact edits and quotations should still read the original source. Interoperation with Headroom's signed exact-retrieval protection would need testing. Source: [search/cache documentation](https://github.com/mksglu/context-mode#smart-snippets).

## Existing bundle overlap

Local inspection found RTK 0.49.0 and Headroom 0.37.0. Headroom already provides local file/command compression and request compression, including deduplication and Kompress on ONNX CPU. Installed supporting packages include ONNX Runtime 1.30.0, tiktoken 0.14.0, tokenizers 0.23.2, transformers 5.17.0 and LiteLLM 1.100.1. Tokenizers count/encode text; installing more tokenizers does not itself reduce Codex consumption.

TOON and LLMLingua were **not** found installed or integrated in this Headroom package. Nevertheless, a separate TOON serialization layer would overlap Headroom's existing recursive JSON/tabular/structural transforms, while another LLMLingua-style token-pruning model would overlap Kompress. Neither is a justified add-on without representative quality and total-request measurements. Do not describe these as already installed.

Context Mode's reusable FTS5 index and data-processing tools are its more distinct features. Its command-output filtering duplicates RTK/local Headroom, and adding it below request Headroom can compress the same evidence twice. Its session-memory and PreCompact hooks should stay out of scope because the user set chat compaction aside.
