"""Run each test family with its isolated installed dependency environment."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# These dependency-light pytest modules use fixtures that unittest cannot run.
# Keep them in the dashboard environment, which already includes pytest.
PYTEST_FILES = (
    'test_bundle_activity.py', 'test_bundle_router.py', 'test_cli_launchers.py',
    'test_cli_observability.py', 'test_cli_tools.py', 'test_headroom_gateway.py',
    'test_laya_guidance.py',
)


def cases(suite):
    for value in suite:
        if isinstance(value, unittest.TestSuite):
            yield from cases(value)
        else:
            yield value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--installed', type=Path)
    parser.add_argument('--suite', choices=['core', 'summary'])
    parser.add_argument('--output', type=Path, default=ROOT / 'logs/verification')
    args = parser.parse_args()
    if args.suite:
        names = (['test_local_summary_engine.py'] if args.suite == 'summary' else
                 [path.name for path in sorted((ROOT / 'tests').glob('test_*.py'))
                  if path.name not in (*PYTEST_FILES, 'test_local_summary_engine.py')])
        suite = unittest.TestSuite(unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern=name)
                                   for name in names)
        selected = [case for case in cases(suite)
                    if args.suite == 'summary' or not case.id().startswith('test_local_summary_engine.')]
        if not selected:
            raise RuntimeError('No tests were discovered for the selected suite.')
        result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(selected))
        print(json.dumps({'suite': args.suite, 'run': result.testsRun, 'failures': len(result.failures),
                          'errors': len(result.errors), 'skipped': len(result.skipped)}))
        return 0 if result.wasSuccessful() else 1
    if args.installed is None:
        parser.error('--installed is required for the complete check')
    args.output.mkdir(parents=True, exist_ok=True)
    installed = args.installed.resolve()
    commands = {
        'core': [str(installed / 'headroom/.venv/Scripts/python.exe'), __file__, '--suite', 'core'],
        'summary': [str(installed / 'local-compaction/.venv/Scripts/python.exe'), __file__, '--suite', 'summary'],
        'bundle': [str(installed / 'dashboard/.venv/Scripts/python.exe'), '-m', 'pytest',
                   *[str(ROOT / 'tests' / name) for name in PYTEST_FILES], '-q'],
        'dashboard': [str(installed / 'dashboard/.venv/Scripts/python.exe'), '-m', 'pytest', 'dashboard/tests', '-q'],
    }
    records = {}
    for name, command in commands.items():
        with (args.output / f'{name}.log').open('wb') as log:
            process = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=600,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        records[name] = {'exit_code': process.returncode}
        print(json.dumps({name: records[name]}), flush=True)
    (args.output / 'result.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    return 0 if all(item['exit_code'] == 0 for item in records.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
