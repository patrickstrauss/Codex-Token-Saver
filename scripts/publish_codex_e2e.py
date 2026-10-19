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


def render(report, raw_name, manifest_name, chart_name=None):
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
    full = meta.get('configuration') == 'full'
    configuration = 'Full coding configuration' if full else 'Explicit-tool pilot'
    lines = ['# Native Codex / Token Saver: ' + configuration.lower(), '',
             f"Run started {report['started_at']}. Five synthetic paired tasks on one Windows laptop.",
             f"Requested model: `{meta['configured_model']}`; reasoning: `{meta['reasoning_effort']}`;",
             f"CLI: `{meta['codex_version']}`; Windows: `{meta['os_version']}` ({meta['architecture']}).", '',
             f'[Raw results]({raw_name}) · [Frozen tasks, hashes and rubric]({manifest_name})', '',
             'Configuration: **' + configuration + '**.', '',
             '## Results', '']
    if chart_name:
        lines += [f'![{configuration}: reported model input, runtime and strict-check counts]({chart_name})', '']
    lines += [
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
    native, bundle = summary['arms']['native'], summary['arms']['bundle']
    if native['uncached_input_tokens'] and native['wall_seconds']:
        lines += [f"Uncached input change: **{(bundle['uncached_input_tokens']/native['uncached_input_tokens']-1)*100:+.2f}%**.",
                  f"Wall time change: **{(bundle['wall_seconds']/native['wall_seconds']-1)*100:+.2f}%**.",
                  'Cache mix differs between arms; these percentages are not interchangeable with cost or quota.', '']
    for row in rows:
        if not row['passed']:
            checks = ', '.join(key for key, value in row['quality'].items()
                               if key != 'passed' and value is False)
            lines.append(f"- `{row['case']}` / {row['arm']}: failed checks: {checks or 'CLI/tool/usage completion' }.")
    lines += ['', 'The fixed rubric checks exact structured answers and unchanged fixtures; the code fix also passes',
              'an independent hidden oracle. Final answer prose, command output and credentials are not published.',
              'Exact-answer failures do not, by themselves, prove a semantic error or a bundle regression.', '',
              '## Scope and limitations', '',
              ('- Explicit tools, automatic Headroom request compression and the reviewed command hook enabled. Browser tasks and other clients excluded.' if full else
               '- Explicit MCP tools only. Automatic request compression, RTK hooks, browser tasks and other clients were excluded.'),
              '- Fresh native-provider sessions and separate identical Git fixtures; deterministic randomized arm order.',
              '- Same model, reasoning setting and permissions in both arms. Plugins, connected apps and multi-agent work disabled.',
              f"- Execution mode: `{meta['sandbox_mode']}`. Temporary synthetic directories are not a VM or security boundary.",
              '- Reported latency includes CLI/MCP startup and model time. Shared workers and provider caches were not flushed.',
              '- All attempts are retained; zero manual retries within this frozen study. Internal network retries are not measured.',
              '- This small sample cannot establish statistical equivalence or predict savings on larger real repositories.',
              f"- Daily authentication/configuration unchanged: `{report['daily_profile_unchanged']}`. VM tests remain paused.", '',
              'Component versions: ' + ', '.join(f"{name} `{version}`" for name, version in meta['bundle_versions'].items()) + '.', '']
    if full:
        automatic = [row.get('automatic_activity', {}) for row in rows if row['arm'] == 'bundle']
        routed = sum(value.get('relay_connections', {}).get('optimized', 0) for value in automatic)
        direct = sum(value.get('relay_connections', {}).get('direct', 0) for value in automatic)
        failed = sum(value.get('relay_connections', {}).get('failed', 0) for value in automatic)
        rewritten = sum(value.get('hook', {}).get('events', {}).get('rewritten', 0) for value in automatic)
        skipped = sum(value.get('hook', {}).get('events', {}).get('skipped', 0) for value in automatic)
        lines += ['## Automatic-path evidence', '',
                  f'{routed} connections routed to Headroom; {direct} direct connections; {failed} relay failures.',
                  f'Command hook: {rewritten} rewrites and {skipped} skips attributed to the benchmark chats.',
                  'A routed connection is not proof of a positive compression event. Direct connections can include metadata requests.',
                  'Relay failure counts can include abrupt client socket shutdown; they do not prove failed model tasks or request retries.',
                  'Shared-backend savings estimates are not attributed to these tasks or added to model usage.',
                  'The temporary production relay used a separate loopback port and the existing warm backend.',
                  'Only the reviewed production hook bypassed trust in temporary CLI profiles; no daily hook trust was changed.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--manifest-name', required=True)
    parser.add_argument('--chart-name')
    args = parser.parse_args()
    report = json.loads(args.input.read_text(encoding='utf-8'))
    args.output.write_text(render(report, args.input.name, args.manifest_name, args.chart_name), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
