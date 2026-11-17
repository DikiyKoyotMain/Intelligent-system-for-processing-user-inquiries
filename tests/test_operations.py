import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from scripts.load_http import local_https_context, percentile, run_profile


class OperationsTests(unittest.TestCase):
    def test_load_tool_rejects_remote_and_unverified_origins(self):
        for origin in ['http://localhost:8000', 'https://example.com', 'https://key@localhost', 'https://localhost/a', 'https://localhost?token=secret']:
            with self.assertRaises(ValueError):
                local_https_context(origin, 'missing.crt')

    def test_invalid_load_bounds_are_rejected_before_network(self):
        for settings in [dict(requests=0), dict(concurrency=100), dict(timeout=31), dict(duration_seconds=0)]:
            with self.assertRaises(ValueError):
                run_profile('https://localhost', 'missing.crt', 'key', **settings)

    def test_load_report_preserves_http_failures_without_payloads(self):
        with patch('scripts.load_http.local_https_context'), patch('scripts.load_http.open_local', side_effect=HTTPError('https://localhost', 429, 'limited', {}, None)):
            report = run_profile('https://localhost', 'unused.crt', 'sensitive-key', requests=8, concurrency=4)
        self.assertEqual(report['status_counts'], {'429': 8})
        self.assertEqual(report['success_rate'], 0)
        self.assertNotIn('sensitive-key', json.dumps(report))
        self.assertNotIn('query', report)

    def test_transport_errors_are_not_successes(self):
        with patch('scripts.load_http.local_https_context'), patch('scripts.load_http.open_local', side_effect=URLError('unavailable')):
            report = run_profile('https://localhost', 'unused.crt', 'key', requests=2, concurrency=1)
        self.assertEqual(report['status_counts'], {'transport_or_decode_error': 2})
        self.assertEqual(report['success_rate'], 0)
        self.assertEqual(percentile([1, 2, 3], .5), 2)
