# Codex Token Saver

A bundle of optional tools that reduces material sent to Codex and reports the resulting activity.

## Language

**Component**: An independently controlled bundle capability, such as RTK command filtering or Headroom request compression. One library can supply more than one component.

**Configured**: Selected for use by the user; this does not establish that a running Codex session has loaded or invoked it.

**Active**: Confirmed available in the current execution path. Recent use is reported separately.

**Bypassed**: An operation intentionally left unchanged because optimization is disabled, unsupported, unnecessary, or requires exact content.

**Local output savings**: Estimated reduction of a file or command result before it enters a conversation.

**Request savings**: Estimated reduction of material in model requests, including repeated conversation history. These overlap local output savings and must not be added to them.

**Exact retrieval**: Recovery of the complete original content rather than a compressed overview.

**Native compaction**: Codex's own conversation compaction. Optional compaction research is separate from the shipped bundle.
