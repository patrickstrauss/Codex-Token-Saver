# Local summary reliability repair

The real conversation test processed only six segments. Its prose incorrectly declared no unresolved errors despite an incomplete failed-command result. Four native compaction records were also reported as skipped conversation content.

## Decisions

The user approved preserving error uncertainty, processing pending batches automatically, and repairing coverage. The existing controller, local model and dashboard remain the implementation; no new library or request routing is needed. A single explicit refresh processes the history snapshot available when the job starts. Later messages wait for another explicit refresh.

The worker keeps one owned model session alive, saves a checkpoint after each successful batch, stops on no progress or failure, and releases the model on completion or cancellation. Cancellation preserves already completed batches. Older summaries require regeneration so previously dropped source evidence is recovered.

The reader scans the full file snapshot with a 16 MiB record bound. Native compaction metadata does not count as missing original messages. Exceptional oversized, malformed and unfinished records remain visible as coverage limitations. Stable original text IDs are preserved.

Grounding separates historical source observations from current resolution and from verified test results. Nonzero exits and incomplete-output cautions persist independently of model prose. These observations are conservative; they are not a general semantic validator and may flag quoted execution-shaped material.

## Verification

Validation passed: 31 controller/reader tests (plus 5 subtests), 18 engine tests, 2 MCP tests and 51 dashboard tests. The real-model regression completed two batches and all 14 checks passed in 130.67 seconds, including failure evidence, preserved constraints, untouched source, cancellation and model exit.

Focused tests cover automatic draining, cancellation and resumption, no-progress termination, persistent process reuse, cleanup despite status-write failures, large checkpoint round trips, format migration, Windows status-reader contention, source snapshots and record coverage. The shipped dashboard script is exercised for explicit start, progress display and incomplete coverage. Engine tests cover local session framing/cleanup and evidence preservation.

`scripts/verify_local_summary.py --installed <bundle> --regression-batches` runs the real installed local model against an isolated multi-batch fixture with a failed command, checks preservation and evidence, then cancels another job and checks shutdown. Local reports are retained under `logs/`; runtime state and conversations are excluded from Git.

Native Codex compaction, provider routing, model/reasoning selection and original conversations remain untouched. Full coverage does not guarantee a lossless summary or measured Codex quota savings.
