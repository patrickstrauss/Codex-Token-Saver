import unittest

from scripts.benchmark_modules import compare_content, summarize_samples


class PerformanceBenchmarkTests(unittest.TestCase):
    def test_exact_recovery_preserves_crlf_and_reports_visible_facts(self):
        result = compare_content('OK\r\nERROR E78\r\n', 'ERROR E78',
                                 'OK\r\nERROR E78\r\n', ['ERROR E78'])
        self.assertTrue(result['passed'])
        self.assertTrue(result['original_identical'])
        self.assertEqual(result['missing_overview_facts'], [])

    def test_changed_original_fails_even_when_critical_fact_survives(self):
        result = compare_content('OK\r\nERROR E78\r\n', 'ERROR E78',
                                 'OK\nERROR E78\n', ['ERROR E78'])
        self.assertFalse(result['passed'])
        self.assertFalse(result['original_identical'])

    def test_missing_overview_fact_fails_even_when_recoverable(self):
        result = compare_content('ERROR E78', 'all good', 'ERROR E78', ['ERROR E78'])
        self.assertFalse(result['passed'])
        self.assertEqual(result['missing_overview_facts'], ['ERROR E78'])
        self.assertEqual(result['missing_recovered_facts'], [])

    def test_bad_fixture_is_rejected(self):
        with self.assertRaises(ValueError):
            compare_content('normal', 'normal', 'normal', ['missing'])

    def test_repeated_measurements_use_medians_and_keep_failure(self):
        result = summarize_samples([
            {'passed': True, 'original_ms': 1, 'optimized_ms': 5},
            {'passed': False, 'original_ms': 3, 'optimized_ms': 9},
            {'passed': True, 'original_ms': 2, 'optimized_ms': 100},
        ])
        self.assertEqual(result['original_median_ms'], 2)
        self.assertEqual(result['optimized_median_ms'], 9)
        self.assertEqual(result['median_added_ms'], 6)
        self.assertFalse(result['passed'])

    def test_no_samples_cannot_report_success(self):
        with self.assertRaises(ValueError):
            summarize_samples([])


if __name__ == '__main__':
    unittest.main()
