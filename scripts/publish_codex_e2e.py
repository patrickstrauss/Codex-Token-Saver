"""Render a complete, sanitized paired coding study without making model calls."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.benchmark_codex_e2e import summarize
from scripts.benchmark_e2e_fixtures import cases


def render(report, raw_name, manifest_name):
    rows = report['samples']
    required = {(case['id'], arm) for case in cases() for arm in ('native', 'bundle')}
    if len(rows) != 10 or {(row['case'], row['arm']) for row in rows} != required:
        raise ValueError('A complete study needs ten unique, paired samples')
    summary = summarize(rows)
    if summary != report['summary'] or not report['complete']:
        raise ValueError('Stored results do not match recomputed totals')
    if any(row['usage'] is None for row in rows):
        raise ValueError('Usage is missing; publish the incomplete diagnostic JSON instead')
    meta = report['metadata']
    lines = ['# Native Codex / Token Saver coding study', '',
             f"Run started {report['started_at']}. Five synthetic paired tasks on one Windows laptop.",
             f"Requested model: `{meta['configured_model']}`; reasoning: `{meta['reasoning_effort']}`;",
             f"CLI: `{meta['codex_version']}`; Windows: `{meta['os_version']}` ({meta['architecture']}).", '',
             f'[Raw results]({raw_name}) · [Frozen tasks, hashes and rubric]({manifest_name})', '',
             '## Results', '',
             '| Task | Native grade | Bundle grade | Native input | Bundle input | Native seconds | Bundle seconds |',
             '|---|---|---|---:|---:|---:|---:|']
    for case in cases():
        pair = {row['arm']: row for row in rows if row['case'] == case['id']}
        native, bundle = pair['native'], pair['bundle']
        lines.append(f"| {case['id']} | {'Pass' if native['passed'] else 'Fail'} | {'Pass' if bundle['passed'] else 'Fail'} | "
                     f"{native['usage']['input_tokens']:,} | {bundle['usage']['input_tokens']:,} | "
                     f"{native['wall_seconds']:.3f} | {bundle['wall_seconds']:.3f} |")
    lines += ['', '| Total | Native | Bundle |', '|---|---:|---:|']
    for label, key in (('Passed tasks', 'passed'), ('Input tokens (including cached)', 'input_tokens'),
                       ('Cached input tokens', 'cached_input_tokens'), ('Uncached input tokens', 'uncached_input_tokens'),
                       ('Output tokens', 'output_tokens'), ('Wall seconds', 'wall_seconds')):
        lines.append(f"| {label} | {summary['arms']['native'][key]:,} | {summary['arms']['bundle'][key]:,} |")
    reduction = summary['input_reduction_percent']
    lines += ['', f"Signed input-token reduction: **{reduction:+.2f}%** (negative means more input with the bundle).",
              'This is reported model input, including cached tokens, across all attempts; failed tasks remain included.',
              'No weekly quota or billing reduction was measured.', '', '## Tool use and quality', '',
              f"The bundle made {summary['bundle_calls']} MCP calls; {summary['bundle_call_failures']} reported failures.",
              'Native commands remain available in both arms. Tool availability does not imply a call to every component.', '']
    for row in rows:
        if not row['passed']:
            checks = ', '.join(key for key, value in row['quality'].items()
                               if key != 'passed' and value is False)
            lines.append(f"- `{row['case']}` / {row['arm']}: failed checks: {checks or 'CLI/tool/usage completion' }.")
    lines += ['', 'The fixed rubric checks exact structured answers and unchanged fixtures; the code fix also passes',
              'an independent hidden oracle. Final answer prose, command output and credentials are not published.',
              'Exact-answer failures do not, by themselves, prove a semantic error or a bundle regression.', '',
              '## Scope and limitations', '',
              '- Explicit MCP tools only. Automatic request compression, RTK hooks, browser tasks and other clients were excluded.',
              '- Fresh native-provider sessions and separate identical Git fixtures; deterministic randomized arm order.',
              '- Same model, reasoning setting and permissions in both arms. Plugins, connected apps and multi-agent work disabled.',
              f"- Execution mode: `{meta['sandbox_mode']}`. Temporary synthetic directories are not a VM or security boundary.",
              '- Reported latency includes CLI/MCP startup and model time. Shared workers and provider caches were not flushed.',
              '- All attempts are retained; zero manual retries within this frozen study. Internal network retries are not measured.',
              '- This small sample cannot establish statistical equivalence or predict savings on larger real repositories.',
              f"- Daily authentication/configuration unchanged: `{report['daily_profile_unchanged']}`. VM tests remain paused.", '',
              'Component versions: ' + ', '.join(f"{name} `{version}`" for name, version in meta['bundle_versions'].items()) + '.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--manifest-name', required=True)
    args = parser.parse_args()
    report = json.loads(args.input.read_text(encoding='utf-8'))
    args.output.write_text(render(report, args.input.name, args.manifest_name), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
