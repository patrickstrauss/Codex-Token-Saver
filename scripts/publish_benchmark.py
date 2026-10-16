"""Render measured, isolated benchmark data; never extrapolate account quota savings."""
import argparse
import json
from pathlib import Path


def render(result):
    if not result.get('passed') or result.get('external_model_calls') != 0 or not result.get('isolated_from_live_ledgers'):
        raise ValueError('Only passing isolated offline measurements can be published')
    rows = ['# Offline benchmark results', '', 'Generated from synthetic fixtures; no Codex/model requests were made.', '',
            '| Case | Native output tokens | Bundle output tokens | Reduction | Added median latency | Net after full retrieval |',
            '|---|---:|---:|---:|---:|---:|']
    for case in [*result['headroom'], dict(result['rtk'], fixture='git diff (RTK)')]:
        before, after = case['original_tokens'], case['optimized_tokens']
        rate = (before - after) / before * 100 if before else 0
        net = case.get('estimated_tokens_avoided_after_full_retrieval')
        rows.append(f"| {case['fixture']} | {before:,} | {after:,} | {rate:.1f}% | {case['median_added_ms']:.3f} ms | {net if net is not None else 'Not measured'} |")
    rows += ['', 'Token estimates use the installed local tokenizer. Cases are separate comparisons and must not be added together.', '',
             'All declared critical facts survived and recovered Headroom originals matched byte for byte. This is a fixture check, not evidence of equal model answer quality.', '',
             'Full retrieval can cost more than reading the original once. Small files can expand because of response headers.', '',
             'This does not measure end-to-end Codex usage, ChatGPT quota, billing, model accuracy, request compression, Laya, Serena, ast-grep, or browser automation.', '',
             'See [methodology](../BENCHMARK.md). Raw data is provided alongside this report.', '']
    return '\n'.join(rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(json.loads(args.input.read_text(encoding='utf-8'))), encoding='utf-8')
