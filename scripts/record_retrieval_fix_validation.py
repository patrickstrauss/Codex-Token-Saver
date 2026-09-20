"""Record tested source evidence without changing Codex routing or live services."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop_proxy_control import CRITICAL_FILES, atomic_write, _encode


def read_json(relative):
    return json.loads((ROOT / relative).read_text(encoding='utf-8-sig'))


def main():
    tested = read_json('logs/retrieval-tested-source-hashes.json')
    for name, expected in tested.items():
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f'Source changed after verification began: {name}')
    if not set(CRITICAL_FILES).issubset(tested):
        raise RuntimeError('Critical source verification is incomplete')
    core = (ROOT / 'logs/retrieval-full-core-tests.log').read_text(encoding='utf-8-sig')
    dashboard = (ROOT / 'logs/retrieval-full-dashboard-tests.log').read_text(encoding='utf-8-sig')
    core_count = re.search(r'Ran (\d+) tests', core)
    dashboard_count = re.search(r'(\d+) passed', dashboard)
    if not core_count or not core.rstrip().endswith('OK') or not dashboard_count:
        raise RuntimeError('Regression verification has not passed')
    if re.search(r'\b(?:failed|errors?)\b', dashboard, re.IGNORECASE):
        raise RuntimeError('Dashboard verification contains failures')
    runtime = read_json('logs/retrieval-runtime-validation.json')
    if not all(runtime.get(name) is True for name in (
        'ok', 'exact_retrieval_protected', 'request_invariants_preserved'
    )):
        raise RuntimeError('Runtime compatibility verification has not passed')
    smoke = read_json('logs/exact-retrieval-live-mcp-smoke.json')
    if not all(smoke.get(name) is True for name in (
        'ok', 'real_mcp_stdio', 'exact_body_verified', 'signed_receipt_verified',
        'real_outer_sdk_transform_verified', 'schema_accepts_12_and_24'
    )) or smoke.get('exact_savings_claimed') != 0:
        raise RuntimeError('Exact retrieval round-trip verification has not passed')
    path = ROOT / 'proxy/validation.json'
    validation = read_json('proxy/validation.json')
    stamp = datetime.now(timezone.utc)
    shutil.copy2(path, ROOT / 'logs' / f'validation-before-retrieval-fix-{stamp:%Y%m%dT%H%M%SZ}.json')
    validation.update(
        passed=True,
        timestamp=stamp.isoformat(),
        source_hashes={name: tested[name] for name in CRITICAL_FILES},
        tests={'core': int(core_count.group(1)), 'dashboard': int(dashboard_count.group(1))},
        retrieval_fix={
            'source_hashes': tested,
            'runtime_compatibility': True,
            'real_mcp_and_sdk_round_trip': True,
            'deployment_at_validation': 'Installed files verified; running MCP and backend require a Windows restart.',
        },
    )
    validation.setdefault('live_checks', {})['exact-retrieval-live-mcp-smoke.json'] = True
    atomic_write(path, _encode(validation))
    print(json.dumps({'passed': True, 'tests': validation['tests'], 'restart_required': True}))


if __name__ == '__main__':
    main()
