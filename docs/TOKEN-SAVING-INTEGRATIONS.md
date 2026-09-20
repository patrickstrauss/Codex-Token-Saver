# Additional token-saving integrations

Reviewed September 14, 2026. Research only: no candidate software installed and no Codex configuration changed. Sources are current project documentation, licenses, release metadata, and selected implementation/CI files. Savings have not been benchmarked on this laptop.

## Recommendation

Pilot **Serena** on one coding project first. Consider **grepai** afterward if semantic search provides an additional benefit. Treat **Codebase Memory MCP** as an alternative to Serena to compare, rather than enabling both immediately. Add **QMD** only for a substantial local document collection.

These tools can reduce how much irrelevant material is read before RTK and Headroom process outputs and requests. Their marginal benefit must be measured against the existing bundle, including their own tool descriptions, retrieval calls, indexing overhead, and exact-content follow-ups.

| Project | License | Potential contribution | Bundle decision |
|---|---|---|---|
| [Serena](https://github.com/oraios/serena) | MIT | Find symbols, inspect selected function bodies, and follow references instead of reading whole files. | First pilot; explicit Codex App documentation and Windows CI. |
| [grepai](https://github.com/yoanbernabeu/grepai) | MIT | Search code by intent using local embeddings; retrieve relevant code regions. | Optional semantic complement; strong native Windows evidence. |
| [Codebase Memory MCP](https://github.com/DeusData/codebase-memory-mcp) | MIT | Query an indexed code graph for functions, callers, dependencies, and architecture. | Compare with Serena; native Windows executable and no mandatory hosted model/API key. |
| [QMD](https://github.com/tobi/qmd) | MIT application | Retrieve selected passages from Markdown and documentation collections. | Optional document feature; Windows validation needed. |
| [CocoIndex Code](https://github.com/cocoindex-io/cocoindex-code) | Apache-2.0 | Incrementally indexed semantic code search. | Alternative to grepai, rather than another default indexer. |

## Integration details

**Serena:** Its [Codex CLI and App instructions](https://github.com/oraios/serena/blob/main/docs/02-usage/030_clients.md#codex-cli-and-app) provide a dedicated Codex context that excludes duplicate file/shell tools. Desktop sessions may start outside the project directory, so activate the actual checkout or worktree explicitly. Start with navigation tools; retain exact source reads before edits. Windows support is exercised in CI, but each enabled language server has its own dependencies. Install only those needed for the selected project. There is no credible universal savings percentage: the project's [Codex evaluation](https://github.com/oraios/serena/blob/main/docs/04-evaluation/030_results/020_codex_on_jbplugin.md) also describes cases where ordinary patches are more efficient, and uses a different backend from the proposed pilot.

**grepai:** Native Windows builds and [Windows CI](https://github.com/yoanbernabeu/grepai/blob/eb941fe8072b7a9af87e2604896456ae16a5127d/.github/workflows/ci.yml) provide concrete platform evidence. Use its [stdio MCP interface](https://github.com/yoanbernabeu/grepai/blob/eb941fe8072b7a9af87e2604896456ae16a5127d/docs/src/content/docs/mcp.md), a local embedding provider such as Ollama, and local index storage. The documented default embedding model is approximately 274 MB to download; that is not a RAM measurement. Validate refreshes after edits and worktree changes. Semantic matches can miss exact identifiers, so retain symbol/text search as fallback.

**Codebase Memory MCP:** The [README](https://github.com/DeusData/codebase-memory-mcp/blob/main/README.md) documents Windows amd64 releases, a persistent code graph, and 15 MCP tools. Codex setup is documented as CLI integration; Desktop operation remains a local validation task. Its installer can modify agent instructions, hooks, and configuration, so use binary-only/manual MCP setup for a controlled comparison. Optional semantic language-server features may add prerequisites. Large upstream reduction claims concern particular structural queries or repository exploration experiments, not incremental savings over this bundle or total Codex task usage.

**QMD:** Its [documentation](https://github.com/tobi/qmd/blob/04e4dbd8245c527a88f1a8f0bda547aef9ca81fb/README.md) covers local keyword/vector search and reranking. The documented three-model download is approximately 2 GB; this is disk usage, not a measured RAM requirement. Model licenses are separate from the MIT application license. Windows dependencies exist, but the reviewed CI omits Windows and the documentation includes a Windows CUDA workaround. Prioritize this only if repeated document reading is a significant workload.

**CocoIndex Code:** Its [README](https://github.com/cocoindex-io/cocoindex-code/blob/47605cf099456ae117bbade9a66c2d5a0f82e416/README.md) documents Codex MCP setup. Local embeddings require the full installation; the slim default uses cloud embeddings. The full dependency installation is described as approximately 1 GB. For a local-only pilot, explicitly select the local embedder and set `COCOINDEX_DISABLE_USAGE_TRACKING=1`; anonymous usage tracking otherwise defaults on. Windows dependency wheels exist, but this candidate was not executed here.

## Exclusions from the default open-source bundle

- **jCodeMunch:** The current [Dual-Use License](https://github.com/jgravelle/jcodemunch-mcp/blob/main/LICENSE) restricts commercial use and redistribution. Do not describe it as unrestricted open source or package it by default.
- **Context Mode:** The current [Elastic License 2.0](https://github.com/mksglu/context-mode/blob/main/LICENSE) makes this source-available. There is also a concrete compatibility concern: during inspection, Desktop's bundled Codex reported 0.154.0-alpha.6.2, while the PATH shim reported 0.117.0. The project's [capability probe](https://github.com/mksglu/context-mode/blob/main/hooks/core/codex-caps.mjs) consults PATH and can turn attempted redirects into command denials on older versions. Its full hook plugin is unsuitable as an automatic default here. Do not add its chat-compaction direction; that work was explicitly set aside.
- **Another prompt compressor:** TOON and LLMLingua were not found installed as separate components, but their proposed roles overlap Headroom's structured-data reduction and Kompress token pruning. An extra layer is not an established incremental gain and needs separate integrity testing.

## Acceptance criteria before enabling a pilot

1. Add a small, project-scoped MCP tool set using the existing bundle's configuration management. Codex documents tool allowlists in its [MCP configuration](https://developers.openai.com/codex/mcp/). Keep optional servers from becoming startup requirements.
2. Resolve the actual checkout/worktree explicitly. Verify indexing exclusions, refresh after edits, deleted-file handling, and cross-project isolation. Avoid indexing generated files or dependency directories by default.
3. Test initial indexing, server exit, Windows restart, and ordinary Codex operations. Prefer on-demand processes unless a watcher demonstrates a useful benefit.
4. Compare the existing RTK + Headroom baseline against baseline + one candidate on representative, repeatable tasks. Keep model, reasoning, source revision, and task requirements consistent. Include code exploration, small edits, larger changes, tests, and an exact-content recovery case.
5. Measure task correctness, total input/output tokens when available, tool overhead, latency, disk footprint, and measured memory. Distinguish estimates from provider-reported usage. Do not add the candidate's advertised percentage to RTK or Headroom savings, or count the same avoided content twice.
6. Expose installation version, update/rollback controls, project/index status, and measured incremental results in the dashboard. Enable broadly only after a repeatable net benefit without reduced correctness.

Further primary-source notes: [symbol tools](research-symbol-tools.md), [local search](research-local-search.md), [Context Mode and overlap](research-context-mode.md).
