# Offline benchmark results

Generated from synthetic fixtures; no Codex/model requests were made.

| Case | Native output tokens | Bundle output tokens | Reduction | Added median latency | Net after full retrieval |
|---|---:|---:|---:|---:|---:|
| records.json | 3,758 | 1,475 | 60.8% | 8.369 ms | -1592 |
| worker.log | 4,997 | 316 | 93.7% | 7.787 ms | -435 |
| small.txt | 10 | 140 | -1300.0% | 5.246 ms | -130 |
| git diff (RTK) | 70 | 70 | 0.0% | 98.523 ms | Not measured |

Token estimates use the installed local tokenizer. Cases are separate comparisons and must not be added together.

All declared critical facts survived and recovered Headroom originals matched byte for byte. This is a fixture check, not evidence of equal model answer quality.

Full retrieval can cost more than reading the original once. Small files can expand because of response headers.

This does not measure end-to-end Codex usage, ChatGPT quota, billing, model accuracy, request compression, Laya, Serena, ast-grep, or browser automation.

See [methodology](../BENCHMARK.md). Raw data is provided alongside this report.
