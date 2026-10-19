"""Real protocol checks in a disposable bundle; no client login or daily profile."""
from pathlib import Path
import unittest

from harness_clients import CLIENTS
from scripts.verify_harness_protocol import qualify


class HarnessStdioTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_adapter_discovers_and_reads_without_client_credentials(self):
        result = await qualify(Path(__file__).resolve().parents[1])
        self.assertTrue(result["passed"])
        reads = [r for r in result["checks"] if r["component"] == "headroom_local"]
        self.assertEqual({r["client"] for r in reads}, set(CLIENTS))
        self.assertTrue(all(r["exact_read_passed"] for r in reads))
        self.assertEqual(len(result["checks"]), len(CLIENTS) + 2)
        self.assertFalse(result["external_client_sessions_tested"])
        self.assertFalse(result["daily_profile_modified"])
        self.assertEqual(result["model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
