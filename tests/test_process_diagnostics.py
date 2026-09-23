"""Read-only support reports identify process ancestry without copying command secrets."""
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows process diagnostics')
class ProcessDiagnosticsTests(unittest.TestCase):
    def test_process_tree_and_unexplained_headroom_are_reported_without_arguments(self):
        script = ROOT / 'Get-Token-Saver-Diagnostics.ps1'
        self.assertTrue(script.is_file(), 'Read-only diagnostic entry point is missing')
        command = r'''
. $args[0]
$root = 'C:\Users\fixture\CodexTokenSaver'
$items = @(
 [pscustomobject]@{ProcessId=1;ParentProcessId=0;Name='Codex.exe';ExecutablePath='C:\Apps\Codex.exe';CommandLine='Codex.exe --token SECRET';WorkingSetSize=1024;CreationDate=$null},
 [pscustomobject]@{ProcessId=2;ParentProcessId=1;Name='python.exe';ExecutablePath=($root+'\headroom\.venv\Scripts\python.exe');CommandLine=($root+'\desktop_mcp.py --token SECRET');WorkingSetSize=2097152;CreationDate=$null},
 [pscustomobject]@{ProcessId=3;ParentProcessId=2;Name='python.exe';ExecutablePath='C:\Python\python.exe';CommandLine='hidden --token SECRET';WorkingSetSize=1048576;CreationDate=$null},
 [pscustomobject]@{ProcessId=4;ParentProcessId=1;Name='headroom.exe';ExecutablePath='C:\Other\headroom.exe';CommandLine='headroom mcp serve --api-key SECRET';WorkingSetSize=5242880;CreationDate=$null},
 [pscustomobject]@{ProcessId=5;ParentProcessId=1;Name='python.exe';ExecutablePath='C:\Python\python.exe';CommandLine='unrelated-job.py SECRET';WorkingSetSize=1048576;CreationDate=$null},
 [pscustomobject]@{ProcessId=6;ParentProcessId=1;Name='python.exe';ExecutablePath=($root+'-unrelated\python.exe');CommandLine='unrelated-job.py SECRET';WorkingSetSize=1048576;CreationDate=$null}
)
Get-TokenSaverProcessSnapshot -Processes $items -BundleRoot $root | ConvertTo-Json -Depth 5
'''
        # Pass a literal script path without constructing a shell invocation from it.
        quoted = "'" + str(script).replace("'", "''") + "'"
        command = command.replace('. $args[0]', '. ' + quoted)
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                capture_output=True, text=True, timeout=20, check=True)
        self.assertNotIn('SECRET', result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual({row['pid'] for row in data}, {2, 3, 4})
        by_id = {row['pid']: row for row in data}
        self.assertEqual(by_id[2]['role'], 'Local file MCP')
        self.assertEqual(by_id[3]['parent_name'], 'python.exe')
        self.assertEqual(by_id[4]['role'], 'Upstream Headroom MCP')
        self.assertFalse(by_id[4]['inside_bundle'])


if __name__ == '__main__':
    unittest.main()
