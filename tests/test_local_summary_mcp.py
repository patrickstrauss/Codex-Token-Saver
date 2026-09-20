import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import local_summary_mcp as mcp
from local_summaries import LocalSummaries


class SummaryMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_access_works_while_summary_generation_is_off(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = LocalSummaries(root, root / 'codex')
            with patch.object(mcp, 'controller', control), patch.object(mcp, 'ROOT', root):
                result = await mcp.call_tool('list_local_summary_tasks', {})
                self.assertFalse(result.isError)
                value = json.loads(result.content[0].text.split('\n', 1)[1])
                self.assertEqual(value['tasks'], [])
                self.assertFalse(value['enabled'])
                self.assertTrue(value['native_compaction_retained'])
                self.assertFalse((root / 'codex').exists())

    async def test_invalid_selection_is_an_error_not_a_guessed_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(mcp, 'controller', LocalSummaries(root, root / 'codex')):
                result = await mcp.call_tool('refresh_local_summary', {'task_id': 'latest'})
                self.assertTrue(result.isError)
                self.assertFalse((root / 'local-compaction/state/job.json').exists())


if __name__ == '__main__':
    unittest.main()
