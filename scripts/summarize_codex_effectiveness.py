"""Combine comparable full-stack repetitions; no model calls or app changes."""
import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.benchmark_codex_e2e import fingerprint, summarize
from scripts.publish_codex_e2e import render


def combine(paths):
    reports, sources, reference, seeds = [], [], None, set()
    stable_metadata = None
    for path in paths:
        path = Path(path)
        raw = path.read_bytes()
        report = json.loads(raw)
        manifest_path = path.with_suffix('.manifest.json')
        manifest = json.loads(manifest_path.read_bytes())
        meta = report['metadata']
        # Reuse the single-study checks; never omit failed attempts.
        render(report, path.name, manifest_path.name)
        if meta.get('configuration') != 'full' or report.get('daily_profile_unchanged') is not True:
            raise ValueError('Only unchanged-profile, full-configuration studies can be combined')
        if fingerprint(manifest) != meta['manifest_sha256'] or manifest['seed'] != meta['seed']:
            raise ValueError('Frozen manifest does not match the report')
        if meta['seed'] in seeds:
            raise ValueError('Duplicate study seed; do not count a run twice')
        seeds.add(meta['seed'])
        for row in report['samples']:
            usage = row['usage']
            if any(type(usage.get(key)) is not int or usage[key] < 0
                   for key in ('input_tokens', 'cached_input_tokens', 'output_tokens')):
                raise ValueError('Missing or invalid token counts')
            if usage['cached_input_tokens'] > usage['input_tokens']:
                raise ValueError('Cached input cannot exceed total input')
            if type(row['wall_seconds']) not in (int, float) or not math.isfinite(row['wall_seconds']) or row['wall_seconds'] < 0:
                raise ValueError('Invalid elapsed time')
        comparable = deepcopy(manifest)
        comparable.pop('seed')
        for case in comparable['cases']:
            if set(case.pop('order')) != {'native', 'bundle'}:
                raise ValueError('Unpaired manifest')
        stable = {key: value for key, value in meta.items() if key not in ('seed', 'manifest_sha256')}
        if reference is not None and (reference != comparable or stable_metadata != stable):
            raise ValueError('Tasks, model, permissions or bundle changed between repetitions')
        reference, stable_metadata = comparable, stable
        sources.append({'report': path.name, 'sha256_utf8_lf': hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest(),
                        'manifest': manifest_path.name, 'manifest_sha256': meta['manifest_sha256'],
                        'seed': meta['seed']})
        reports.append(report)
    if not reports:
        raise ValueError('At least one complete study is required')
    rows = [row for report in reports for row in report['samples']]
    result = summarize(rows)
    for arm in result['arms'].values():
        arm['input_plus_output_tokens'] = arm['input_tokens'] + arm['output_tokens']
        arm['uncached_input_plus_output_tokens'] = arm['uncached_input_tokens'] + arm['output_tokens']
    native, bundle = result['arms']['native'], result['arms']['bundle']
    changes = {key: round((bundle[key] / native[key] - 1) * 100, 2) if native[key] else None
               for key in ('input_tokens', 'uncached_input_tokens', 'output_tokens',
                           'input_plus_output_tokens', 'uncached_input_plus_output_tokens', 'wall_seconds')}
    all_passed = all(row['passed'] for row in rows)
    metrics = [changes[key] for key in ('input_tokens', 'uncached_input_tokens',
                                      'input_plus_output_tokens', 'uncached_input_plus_output_tokens')]
    verdict = ('increased' if all(value is not None and value > 0 for value in metrics) else
               'decreased' if all(value is not None and value < 0 for value in metrics) else 'mixed')
    return dict(schema_version=1, studies=sources, repetitions=len(reports), distinct_tasks=5,
                paired_attempts=len(rows) // 2, summary=result, change_percent=changes,
                all_quality_checks_passed=all_passed, token_direction=verdict,
                token_saving_demonstrated=all_passed and verdict == 'decreased',
                limits=['Repeated synthetic tasks on one laptop, not independent real-world workloads.',
                        'Reported CLI usage; no account quota or billing savings measured.',
                        'Warm workers and provider caches not flushed; no causal component attribution.'])


def markdown(result):
    n, b = (result['summary']['arms'][arm] for arm in ('native', 'bundle'))
    if result['token_saving_demonstrated']:
        interpretation = ('The tested configuration reduced both total and uncached token counts with all quality checks passing. '
                          'This is evidence for these tasks only; account quota or billing benefits were not measured.')
    elif result['token_direction'] == 'increased' and result['all_quality_checks_passed']:
        interpretation = ('The current full configuration fails its token-reduction objective on this workload. '
                          'No overall token-saving benefit is demonstrated. Do not advertise a measured net token or quota reduction.')
    else:
        interpretation = ('A token-saving benefit at equivalent checked quality is not established. '
                          'Mixed token metrics or failed quality checks require separate examination.')
    lines = ['# Overall token effectiveness', '',
             f"**The tested bundle configuration {result['token_direction']} reported token usage.**",
             f"{result['repetitions']} full-configuration repetitions; {result['paired_attempts']} paired attempts of five distinct synthetic tasks.",
             'All attempts are included. These are repeated tasks, not ten independent workloads.', '',
             '| Metric | Native | Bundle | Bundle change |', '|---|---:|---:|---:|']
    for label, key in (('Input, including cached', 'input_tokens'), ('Uncached input', 'uncached_input_tokens'),
                       ('Output', 'output_tokens'), ('Input + output', 'input_plus_output_tokens'),
                       ('Uncached input + output', 'uncached_input_plus_output_tokens'), ('Wall seconds', 'wall_seconds')):
        change = result['change_percent'][key]
        lines.append(f"| {label} | {n[key]:,} | {b[key]:,} | {change:+.2f}% |" if change is not None else
                     f"| {label} | {n[key]:,} | {b[key]:,} | Undefined baseline |")
    lines += [f"| Passed attempts | {n['passed']}/{n['attempts']} | {b['passed']}/{b['attempts']} | |", '',
              '## Interpretation', '',
              interpretation, '',
              'Local tool-output savings estimates do not replace the measured end-to-end result.', '',
              'Both arms use the same native model, effort, permissions and fixtures. Treatment adds explicit bundle',
              'tools, automatic Headroom request compression and the reviewed command hook. Quality checks include',
              'exact structured answers, unchanged fixtures and an independent hidden oracle for the code fix.', '',
              'Input includes cached tokens; uncached input is shown separately. Input plus output is an unweighted',
              'token count, not a price or quota estimate. Warm caches differ; time includes tool startup and model time.',
              'These small repeated tasks cannot establish results for larger real-world workloads.', '',
              'This is a net configuration comparison, not a component ablation. The data cannot attribute the increase',
              'to Laya, schemas, tool choices, retrieval, hooks or compression separately. Next optimization tests should',
              'compare lean tool exposure and automatic-only configurations against this same frozen baseline.', '',
              '## Evidence', '']
    for source in result['studies']:
        stem = Path(source['report']).stem
        lines += [f"- [Study, seed {source['seed']}]({stem}.md), [raw attempts]({source['report']}), [frozen manifest]({source['manifest']})."]
    lines += ['', '[Machine-readable aggregate](effectiveness-windows.json). Source hashes are recorded there.',
              'Report digests use UTF-8 with LF line endings so Windows checkout conversion does not change provenance.',
              'The earlier [explicit-tool pilot](coding-windows.md) is separate and excluded from this aggregate:',
              'it used a different configuration and an ambiguous exact-answer format. Diagnostic pilots are also',
              'separate. No failed or inconvenient attempt from either full study was discarded.', '',
              'VM acceptance tests remain paused. No daily route, hook trust or authentication was changed.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--markdown', type=Path, required=True)
    args = parser.parse_args()
    result = combine(args.inputs)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    args.markdown.write_text(markdown(result), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
