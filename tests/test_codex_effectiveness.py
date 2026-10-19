from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.benchmark_codex_e2e import fingerprint, summarize
from scripts.summarize_codex_effectiveness import combine, markdown

ROOT = Path(__file__).resolve().parents[1]


class EffectivenessTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.report = json.loads((ROOT / 'docs/benchmarks/overall-windows.json').read_bytes())
        self.manifest = json.loads((ROOT / 'docs/benchmarks/overall-windows.manifest.json').read_bytes())

    def save(self, name='one', seed=1, mutate=None, manifest_mutate=None):
        report, manifest = deepcopy(self.report), deepcopy(self.manifest)
        manifest['seed'] = seed
        if manifest_mutate:
            manifest_mutate(manifest)
        report['metadata'].update(seed=seed, manifest_sha256=fingerprint(manifest))
        if mutate:
            mutate(report)
        path = Path(self.folder.name) / (name + '.json')
        path.write_text(json.dumps(report))
        path.with_suffix('.manifest.json').write_text(json.dumps(manifest))
        return path

    def test_repeated_attempts_are_summed_not_averaged_or_counted_as_distinct_tasks(self):
        result = combine([self.save(), self.save('two', seed=2)])
        self.assertEqual(result['paired_attempts'], 10)
        self.assertEqual(result['distinct_tasks'], 5)
        self.assertEqual(result['summary']['arms']['native']['input_tokens'], 207312 * 2)
        self.assertEqual(result['summary']['arms']['bundle']['input_tokens'], 325089 * 2)
        self.assertEqual(result['change_percent']['input_tokens'], 56.81)
        self.assertEqual(result['token_direction'], 'increased')
        self.assertFalse(result['token_saving_demonstrated'])
        self.assertIn('fails its token-reduction objective', markdown(result))

    def test_duplicate_seed_or_file_cannot_be_counted_twice(self):
        path = self.save()
        for paths in ([path, path], [path, self.save('two')]):
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                combine(paths)

    def test_report_digest_survives_windows_git_line_ending_conversion(self):
        path = self.save()
        pretty = json.dumps(json.loads(path.read_bytes()), indent=2) + '\n'
        path.write_bytes(pretty.encode())
        lf = combine([path])['studies'][0]['sha256_utf8_lf']
        path.write_bytes(pretty.replace('\n', '\r\n').encode())
        self.assertEqual(combine([path])['studies'][0]['sha256_utf8_lf'], lf)

    def test_changed_workload_or_configuration_cannot_be_pooled(self):
        first = self.save()
        changed = self.save('two', 2, manifest_mutate=lambda m: m['cases'][0].update(prompt='different'))
        with self.assertRaisesRegex(ValueError, 'changed'):
            combine([first, changed])
        changed = self.save('two', 2, mutate=lambda r: r['metadata'].update(configured_model='different'))
        with self.assertRaisesRegex(ValueError, 'changed'):
            combine([first, changed])

    def test_stale_summary_and_missing_usage_cannot_produce_a_verdict(self):
        for mutate in (lambda r: r['summary']['arms']['native'].update(input_tokens=1),
                       lambda r: r['samples'][0].update(usage=None)):
            with self.assertRaises((ValueError, TypeError)):
                combine([self.save(mutate=mutate)])

    def test_manifest_hash_mismatch_and_changed_daily_profile_are_rejected(self):
        for mutate in (lambda r: r['metadata'].update(manifest_sha256='wrong'),
                       lambda r: r.update(daily_profile_unchanged=False)):
            with self.assertRaises(ValueError):
                combine([self.save(mutate=mutate)])

    def test_failed_quality_remains_in_totals_and_prevents_savings_claim(self):
        def change(report):
            for row in report['samples']:
                if row['arm'] == 'bundle':
                    row['usage'].update(input_tokens=100, cached_input_tokens=50, output_tokens=1)
            report['samples'][0]['passed'] = False
            report['summary'] = summarize(report['samples'])
        result = combine([self.save(mutate=change)])
        self.assertEqual(result['summary']['arms']['bundle']['attempts'], 5)
        self.assertEqual(result['summary']['arms']['bundle']['passed'], 4)
        self.assertEqual(result['token_direction'], 'decreased')
        self.assertFalse(result['token_saving_demonstrated'])
        self.assertIn('not established', markdown(result))


if __name__ == '__main__':
    unittest.main()
