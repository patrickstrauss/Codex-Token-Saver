# Overall token effectiveness

**The tested bundle configuration increased reported token usage.**
2 full-configuration repetitions; 10 paired attempts of five distinct synthetic tasks.
All attempts are included. These are repeated tasks, not ten independent workloads.

| Metric | Native | Bundle | Bundle change |
|---|---:|---:|---:|
| Input, including cached | 400,705 | 685,590 | +71.10% |
| Uncached input | 172,097 | 216,598 | +25.86% |
| Output | 3,436 | 4,936 | +43.66% |
| Input + output | 404,141 | 690,526 | +70.86% |
| Uncached input + output | 175,533 | 221,534 | +26.21% |
| Wall seconds | 167.904 | 292.659 | +74.30% |
| Passed attempts | 10/10 | 10/10 | |

## Interpretation

The current full configuration fails its token-reduction objective on this workload. No overall token-saving benefit is demonstrated. Do not advertise a measured net token or quota reduction.

Local tool-output savings estimates do not replace the measured end-to-end result.

Both arms use the same native model, effort, permissions and fixtures. Treatment adds explicit bundle
tools, automatic Headroom request compression and the reviewed command hook. Quality checks include
exact structured answers, unchanged fixtures and an independent hidden oracle for the code fix.

Input includes cached tokens; uncached input is shown separately. Input plus output is an unweighted
token count, not a price or quota estimate. Warm caches differ; time includes tool startup and model time.
These small repeated tasks cannot establish results for larger real-world workloads.

This is a net configuration comparison, not a component ablation. The data cannot attribute the increase
to Laya, schemas, tool choices, retrieval, hooks or compression separately. Next optimization tests should
compare lean tool exposure and automatic-only configurations against this same frozen baseline.

## Evidence

- [Study, seed 20261019](overall-windows.md), [raw attempts](overall-windows.json), [frozen manifest](overall-windows.manifest.json).
- [Study, seed 20261020](overall-repeat-windows.md), [raw attempts](overall-repeat-windows.json), [frozen manifest](overall-repeat-windows.manifest.json).

[Machine-readable aggregate](effectiveness-windows.json). Source hashes are recorded there.
Report digests use UTF-8 with LF line endings so Windows checkout conversion does not change provenance.
The earlier [explicit-tool pilot](coding-windows.md) is separate and excluded from this aggregate:
it used a different configuration and an ambiguous exact-answer format. Diagnostic pilots are also
separate. No failed or inconvenient attempt from either full study was discarded.

VM acceptance tests remain paused. No daily route, hook trust or authentication was changed.
