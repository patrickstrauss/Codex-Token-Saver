# Component control review — 2026-09-20

Historical review of retained components: bundle preferences, native RTK mapping, local Headroom filtering and dashboard component routes. See [the current bundle guide](USING-BUNDLE.md) for supported features.

Confirmed defects repaired:

- Native/hook `File.Exists` treated an invalid preferences directory as an absent file, restoring default compression while Python/dashboard reported disabled preferences. Native now opens the file directly; the hook checks attributes. Only actual missing-path exceptions use initial defaults; other read/schema errors bypass filtering.
- Native/hook readers accepted UTF-16 settings while the Python reader rejected them. All three now require UTF-8, optionally with a UTF-8 BOM. Native decoder errors and malformed schemas bypass filtering. BOM checks use ordinal comparison.
- A configuration edit during component preference writing could be overwritten. The integration controller now rechecks the original configuration immediately before replacement and rolls the component preference back on conflict.

Verified behavior:

- RTK Off forwards supported external command arguments through upstream unfiltered proxy mode; original stdin, stderr and exit status are retained. RTK-only verbs without a safe native mapping fail clearly. `HEADROOM_EXACT` bypasses the secondary Headroom stdout stage; it does not disable RTK's own filtering or managed request compression.
- Local Headroom Off returns original file/command content and leaves previous original-content retrieval available. Runtime preferences are read for each operation. The separate request proxy retains its own controls and connection-lifetime limitations.
- Dashboard component mutations reuse the existing loopback Host, Origin and CSRF checks. Frontend status text uses `textContent`, not HTML interpolation.
- An isolated Windows experiment did not reproduce the suspected virtual-environment descendant cleanup escape: closing the assigned Job Object stopped the launcher and real interpreter. No speculative process-creation rewrite was introduced.

Regression evidence: native directory/UTF-16 preference defects failed before repair. Final targeted checks passed: 9 native RTK tests, 3 hook preference tests and 5 Python preference tests. The root task performs final combined verification and deployment. No production routing or configuration was changed by this review.

This review establishes these tested behaviors, not a guarantee that lossy compression preserves every future LLM answer. Exact-content paths and the separate quality checks remain necessary.
