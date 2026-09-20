"""Both cache formats must retrieve exact text without mixing accounting."""
import asyncio
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from desktop_headroom import DesktopHeadroom
from exact_retrieval import sign_exact_response, exact_response_is_verified


class RetrievalBridgeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.original = '\ufeffไทย 漢字 😀\r\nsecond line\nlast line'
        self.cache = SimpleNamespace(retrieve=lambda key: SimpleNamespace(original_content=self.original))
        self.service = DesktopHeadroom(self.root / 'state', token_counter=len, cache=self.cache)
        self.reader = self.enterContext(patch('desktop_headroom.read_proxy_original',
                                             return_value=self.original, create=True))
        self.enterContext(patch('desktop_headroom.sign_exact_response',
                                side_effect=lambda text: sign_exact_response(text, root=self.root), create=True))

    def test_proxy_hash_routes_to_proxy_and_preserves_original(self):
        response = self.service.retrieve('ABCDEF123456')
        self.reader.assert_called_once_with('abcdef123456')
        self.assertEqual(response.split('\n\n', 1)[1], self.original)

    def test_proxy_original_pages_preserving_line_endings(self):
        response = self.service.retrieve('abcdef123456', start_line=2, max_lines=1)
        self.assertEqual(response.split('\n\n', 1)[1], 'second line\n')
        self.assertIn('Lines 2-2 of 3', response)

    def test_proxy_retrieval_does_not_change_local_savings(self):
        before = self.service.stats()
        self.service.retrieve('abcdef123456')
        self.assertEqual(self.service.stats(), before)

    def test_local_hash_still_uses_local_cache_and_accounts_retrieval(self):
        response = self.service.retrieve('a' * 24)
        self.reader.assert_not_called()
        self.assertEqual(response.split('\n\n', 1)[1], self.original)
        self.assertEqual(self.service.stats()['retrieve_count'], 1)

    def test_both_retrieval_types_are_authenticated_exact_responses(self):
        for key in ('abcdef123456', 'a' * 24):
            with self.subTest(key=key):
                self.assertTrue(exact_response_is_verified(self.service.retrieve(key), root=self.root))

    def test_expired_proxy_reference_is_an_error_not_empty_text(self):
        self.reader.side_effect = LookupError('Original not found or expired')
        with self.assertRaisesRegex(LookupError, 'expired'):
            self.service.retrieve('abcdef123456')

    def test_invalid_ranges_are_rejected_before_fetch(self):
        for kwargs in ({'start_line': 0}, {'start_line': True}, {'max_lines': 0},
                       {'max_lines': 10001}, {'max_lines': '3'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.service.retrieve('abcdef123456', **kwargs)
        self.reader.assert_not_called()

    def test_invalid_reference_never_reaches_proxy(self):
        for key in ('../abcdef123456', 'https://example.test', 'z' * 12, 'a' * 13, '', None):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.service.retrieve(key)
        self.reader.assert_not_called()

    def test_explicit_exact_file_read_is_authenticated_and_unchanged(self):
        source = self.root / 'original.txt'
        source.write_bytes(self.original.encode('utf-8'))
        response = self.service.read_file(str(source), compress=False)
        self.assertEqual(response.split('\n\n', 1)[1], self.original)
        self.assertTrue(exact_response_is_verified(response, root=self.root))

    def test_mcp_schema_accepts_both_formats_but_no_urls(self):
        import desktop_mcp
        tools = asyncio.run(desktop_mcp.list_tools())
        tool = next(item for item in tools if item.name == 'headroom_retrieve')
        pattern = tool.inputSchema['properties']['content_hash']['pattern']
        for key in ('abcdef123456', 'a' * 24, 'ABCDEF123456'):
            self.assertIsNotNone(re.fullmatch(pattern, key))
        for key in ('https://example.test', 'z' * 12, 'a' * 13):
            self.assertIsNone(re.fullmatch(pattern, key))


if __name__ == '__main__':
    unittest.main()
