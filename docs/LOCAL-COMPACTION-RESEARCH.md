# Local conversation compaction research

Historical investigation, retained for optional native compaction research. Its runtime recommendations are not part of the current bundle or fresh installation; use [the current bundle guide](USING-BUNDLE.md) for supported features. Existing user models and saved summaries are retained.

Researched 2026-09-14. Research only: no model installation, routing changes, or service changes.

**Conclusion:** Local summarization is feasible as an additional component. Replacing Codex Desktop's native compaction automatically is not a verified drop-in capability. The recommended first experiment is LangMem with a local inference server, integrated into the existing managed gateway, while retaining native compaction as fallback.

## What is already installed

The bundle runs Headroom 0.37.0 with local Kompress ONNX inference, deduplication, and content compression. This is token selection/pruning, not a generative model writing a running conversation summary. The installed pipeline explicitly retired its former rolling-window history-dropping stage and leaves the message list intact. Its introductory rolling-window description is stale. [Headroom pipeline](https://github.com/headroomlabs-ai/headroom/blob/v0.37.0/headroom/transforms/pipeline.py#L90-L98), [configuration](https://github.com/headroomlabs-ai/headroom/blob/v0.37.0/headroom/config.py#L672-L675).

Local hardware inspection found approximately 31.5 GiB RAM, an Intel Core Ultra 7 258V and Intel Arc 140V integrated graphics. Windows' reported adapter RAM is not a reliable dedicated-VRAM measurement. Existing GGUF models are present in LM Studio, but no local inference server was observed running. A small quantized model is a realistic pilot; latency, memory use and summary fidelity remain unmeasured.

## Open-source candidates

| Project | License | Role and assessment |
|---|---|---|
| [LangMem](https://github.com/langchain-ai/langmem) | MIT | Best reusable summarization component. Maintains a running summary, summarizes older messages at a threshold, and retains recent context. Requires a Codex-specific message adapter and per-task state; it is not a standalone desktop integration. |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | MIT | Preferred inference-runtime candidate for this bundle: local GGUF execution, an OpenAI-compatible server, and Vulkan/SYCL support. Pair with a summarization library. Windows/Intel performance must be benchmarked. |
| [Ollama](https://github.com/ollama/ollama) | MIT | Alternative local inference service with a native Windows application and localhost API. Convenient model management; it does not perform conversation compaction by itself. Do not assume accelerated Intel graphics support without testing. |
| [Context Gateway](https://github.com/Compresr-ai/Context-Gateway) | Apache-2.0 | Closest existing background-summary proxy. Supports preemptive summarization and a configurable LLM endpoint, and its CI includes a Windows amd64 build. The default fast setup uses hosted Compresr, so local-only operation needs deliberate configuration. No verified turnkey Codex Desktop Responses/WebSocket/native-compaction support. |
| [Microsoft ACON](https://github.com/microsoft/acon) | MIT | Research framework for agent-history compression and compressor distillation. Useful techniques, but substantially more development/training work than the above options. |

Primary implementation references: [LangMem summarization guide](https://langchain-ai.github.io/langmem/guides/summarization/), [LangMem message handling](https://github.com/langchain-ai/langmem/blob/main/src/langmem/short_term/summarization.py), [Context Gateway summarizer](https://github.com/Compresr-ai/Context-Gateway/blob/main/internal/preemptive/summarizer.go), [custom LLM client](https://github.com/Compresr-ai/Context-Gateway/blob/main/external/llm.go), [Windows build](https://github.com/Compresr-ai/Context-Gateway/blob/main/.github/workflows/build-test.yml), [Ollama Windows documentation](https://docs.ollama.com/windows).

[Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) is a possible small-model benchmark candidate; its publisher metadata declares Apache-2.0. Model licensing is separate from runtime licensing. Neither this model nor the existing local models have been evaluated here for faithful task summaries.

Other popular tools solve different problems. [LLMLingua-2](https://github.com/microsoft/LLMLingua) performs local token pruning and substantially overlaps the current Kompress role. [Context Mode](https://github.com/mksglu/context-mode#license) currently uses Elastic License 2.0: source-available, not OSI open source. Its Codex hooks preserve/recover memory around native compaction rather than replace its inference engine.

## Codex compatibility constraint

The installed binary identifies itself as 0.135.0-alpha.14. Its exact public source tag was unavailable. Stable 0.135.0 and pinned public main were inspected; their behavior must not be assumed identical to this installed alpha.

Official configuration documents thresholds and compaction-prompt overrides, but no separate local compaction-model/provider setting. Changing the whole session to an OSS provider would also change the primary model, contrary to the user's preference. [Official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

Codex's code named "local compaction" still uses its current model client/model; the word local describes orchestration, not necessarily on-device inference. Actual compaction installs replacement history and recomputes token accounting. Merely rewriting an outgoing proxy request does not perform that internal history replacement, though reduced server-reported usage may affect later thresholds. [Model client selection](https://github.com/openai/codex/blob/rust-v0.135.0/codex-rs/core/src/compact.rs#L193-L223), [current model](https://github.com/openai/codex/blob/rust-v0.135.0/codex-rs/core/src/compact.rs#L540-L559), [history replacement](https://github.com/openai/codex/blob/rust-v0.135.0/codex-rs/core/src/compact_remote.rs#L250-L263).

There are two remote protocols. The legacy `/responses/compact` path accepts a list of response items; its implementation retains plain assistant/user messages, making a local-summary bridge technically conceivable. That is undocumented integration behavior requiring version gating and isolated tests. [Legacy handling](https://github.com/openai/codex/blob/rust-v0.135.0/codex-rs/core/src/compact_remote.rs#L270-L332).

Compaction v2 uses ordinary Responses streaming and requires exactly one compaction item, whose protocol contains encrypted content. A local model cannot simply substitute a plain summary for that item. Intercepting only `/responses/compact` therefore does not cover all compaction. Current PreCompact hooks only continue or stop; they do not expose supported replacement-history injection. [V2 validation, pinned main](https://github.com/openai/codex/blob/3abbf9fe2c6b6910e9de61f6a0c5bb468f74b5c8/codex-rs/core/src/compact_remote_v2.rs#L364-L480), [protocol item](https://github.com/openai/codex/blob/rust-v0.135.0/codex-rs/protocol/src/models.rs#L893-L901), [hook outcomes](https://github.com/openai/codex/blob/3abbf9fe2c6b6910e9de61f6a0c5bb468f74b5c8/codex-rs/core/src/hook_runtime.rs#L537-L567), [official compaction explanation](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide#compaction).

## Recommended evaluation

Use LangMem with llama.cpp, or Ollama if easier operationally, inside the existing managed transport. Begin with background summaries of older visible history, preserve recent turns and complete tool-call/result pairs, keep original content retrievable, and isolate state by task. Preserve the user's main model, reasoning, instructions and approvals. Keep native compaction enabled until the installed protocol and client accounting have been validated.

Compare against the current Headroom baseline using actual upstream input usage, native-compaction frequency, end-to-end latency, memory use and task correctness. Do not infer quota or cost savings directly from the existing estimated compression counter. A local summary also consumes compute and adds summary tokens; its net value must be measured.

One prerequisite surfaced during research: request compression emits 12-character CCR references, while the exposed local-file retrieval MCP expects 24-character hashes. Originals remain accessible through the backend's read-only `/v1/retrieve/{hash}` endpoint, but the current tool bridge is incomplete. Resolve that retrieval mismatch before adding more aggressive compaction. Do not disable native compaction or add another global proxy based only on this research.

General web search was unavailable during this investigation. Evidence came from official OpenAI documentation tools, direct project GitHub APIs/source files, publisher model metadata, and read-only local inspection.
