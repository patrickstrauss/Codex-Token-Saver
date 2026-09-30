import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import local_summary_mcp as mcp
from local_summaries import LocalSummaries
from bundle_preferences import set_preference


class SummaryMCPTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch('bundle_router.classify', side_effect=AssertionError('Typed calls do not classify')))

    async def test_read_access_works_while_summary_generation_is_off(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            set_preference(root, 'laya_router', True)
            set_preference(root, 'local_summaries', True)
            control = LocalSummaries(root, root / 'codex')
            with patch.object(mcp, 'controller', control), patch.object(mcp, 'ROOT', root):
                result = await mcp.call_tool('list_local_summary_tasks', {})
                self.assertFalse(result.isError)
                value = json.loads(result.content[0].text.split('\n', 1)[1])
                self.assertEqual(value['tasks'], [])
                self.assertTrue(value['enabled'])
                self.assertFalse(value['model_enabled'])
                self.assertTrue(value['native_compaction_retained'])
                self.assertFalse((root / 'codex').exists())

    async def test_invalid_selection_is_an_error_not_a_guessed_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            set_preference(root, 'laya_router', True)
            set_preference(root, 'local_summaries', True)
            with patch.object(mcp, 'controller', LocalSummaries(root, root / 'codex')), patch.object(mcp, 'ROOT', root):
                result = await mcp.call_tool('refresh_local_summary', {'task_id': 'latest'})
                self.assertTrue(result.isError)
                self.assertFalse((root / 'local-compaction/state/job.json').exists())


if __name__ == '__main__':
    unittest.main()
