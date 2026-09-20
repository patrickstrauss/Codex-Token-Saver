"""Exercise the real background controller against a synthetic, isolated transcript."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import time

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from bundle_preferences import set_preference
from local_summaries import LocalSummaries


def listening():
    with socket.socket() as sock:
        sock.settimeout(.2)
        return sock.connect_ex(('127.0.0.1', 8791)) == 0


def verify(installed, regression_batches=False):
    if listening():
        raise RuntimeError('Summary port is occupied; existing service left untouched.')
    with tempfile.TemporaryDirectory(prefix='bundle-summary-smoke-') as directory:
        root = Path(directory).resolve()
        assert root.is_relative_to(Path(tempfile.gettempdir()).resolve())
        for name in ('local_summaries.py', 'local_summary_engine.py', 'component_runtime.py',
                     'bundle_preferences.py', 'desktop_proxy_control.py'):
            shutil.copy2(SOURCE / name, root / name)
        if regression_batches:
            # Exercise multiple controller batches without a long real conversation.
            controller_source = root / 'local_summaries.py'
            controller_source.write_text(controller_source.read_text(encoding='utf-8').replace(
                'MAX_BATCH_BYTES = 20000', 'MAX_BATCH_BYTES = 6000'), encoding='utf-8')
        venv = root / 'local-compaction/.venv'
        (venv / 'Scripts').mkdir(parents=True)
        (venv / 'Lib/site-packages').mkdir(parents=True)
        for name in ('Scripts/python.exe', 'pyvenv.cfg'):
            shutil.copy2(installed / 'local-compaction/.venv' / name, venv / name)
        (venv / 'Lib/site-packages/installed-runtime.pth').write_text(
            str(installed / 'local-compaction/.venv/Lib/site-packages'), encoding='utf-8')
        binary = root / 'local-compaction/llama-b10809'
        binary.mkdir()
        for source in (installed / 'local-compaction/llama-b10809').iterdir():
            if source.is_file():
                try:
                    os.link(source, binary / source.name)
                except OSError:
                    shutil.copy2(source, binary / source.name)
        shutil.copy2(installed / 'local-compaction/model.json', root / 'local-compaction/model.json')
        set_preference(root, 'local_summaries', True)
        set_preference(root, 'llama_cpp', True)
        home = root / 'codex'
        folder = home / 'sessions/2026/09/20'
        folder.mkdir(parents=True)
        ident = '00000000-0000-4000-8000-000000000001'
        path = folder / f'rollout-2026-09-20T12-00-00-{ident}.jsonl'
        rows = [{'type': 'session_meta', 'payload': {'id': ident, 'cwd': 'C:/fixture'}}]
        messages = [
            ('user', 'Implement the bundle. Preserve gpt-6-astra and ultra. Never delete backups. Keep native compaction enabled. Do not send transcripts to cloud services.'),
            ('assistant', 'Serena read-only navigation passed 10 tests. The summary dashboard is unfinished. Next: verify restart.'),
            ('user', 'Retain the constraints above. Local model memory must be released after the job.'),
        ]
        rows.extend({'type': 'response_item', 'payload': {'type': 'message', 'role': role,
                     'content': [{'type': 'input_text', 'text': text}]}} for role, text in messages)
        if regression_batches:
            rows.extend([
                {'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': 'failed-build',
                    'name': 'exec', 'arguments': '{}'}},
                {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'failed-build',
                    'output': json.dumps({'chunk_id': 'regression-build', 'wall_time_seconds': .5,
                        'exit_code': 1, 'output': 'Build output truncated. ' + 'diagnostic detail ' * 400})}},
                {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [
                    {'text': 'The earlier command failure has not been investigated. Keep verification pending. Preserve the model, backups and native compaction constraints.'}]}}
            ])
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        original = hashlib.sha256(path.read_bytes()).hexdigest()
        controller = LocalSummaries(root, home)
        job = controller.start(ident)
        started = time.monotonic()
        while controller.status()['running']:
            if time.monotonic() - started > (480 if regression_batches else 240):
                controller.cancel(ident)
                deadline = time.monotonic() + 30
                while controller.status()['running'] and time.monotonic() < deadline:
                    time.sleep(.2)
                raise TimeoutError('Synthetic summary exceeded the validation time limit.')
            time.sleep(.5)
        result = controller.get_summary(ident)
        first_job = controller.status()['job']
        diagnostic = SOURCE / 'logs/summary-regression-diagnostic.json'
        if regression_batches:
            diagnostic.parent.mkdir(exist_ok=True)
            diagnostic.write_text(json.dumps({'job': first_job, 'summary': result}), encoding='utf-8')
        text = (result['summary'] or '').lower()
        checks = {'completed': result['status'] == 'summarized',
                  'model_preserved': 'gpt-6-astra' in text and 'ultra' in text,
                  'constraints_retained': 'backup' in text and 'compaction' in text,
                  'pending_work_retained': 'restart' in text and ('unfinished' in text or 'dashboard' in text),
                  'original_unchanged': hashlib.sha256(path.read_bytes()).hexdigest() == original,
                  'model_unloaded': not listening(),
                  'all_messages_covered': result['coverage']['pending_messages'] == 0}
        if regression_batches:
            artifact_path = controller._saved_path(ident)
            artifact = json.loads(artifact_path.read_text(encoding='utf-8')) if artifact_path.exists() else {}
            evidence = artifact.get('running_summary', {}).get('evidence', {})
            checks['automatic_batches'] = controller.status()['job'].get('batches_completed', 0) >= 2
            checks['failure_evidence_retained'] = 1 in evidence.get('nonzero_exit_codes', [])
            checks['incomplete_evidence_retained'] = evidence.get('incomplete_source') is True
            checks['evidence_visible'] = 'source evidence' in text and 'exit' in text
        # Start a second real worker and cancel it; queued/running cancellation is explicit.
        path.write_text(path.read_text() + json.dumps({'type': 'response_item', 'payload': {
            'type': 'message', 'role': 'user', 'content': [{'text': 'Next check is cancellation.'}]}}) + '\n')
        controller.start(ident)
        deadline = time.monotonic() + 35
        while not listening() and controller.status()['running'] and time.monotonic() < deadline:
            time.sleep(.1)
        controller.cancel(ident)
        deadline = time.monotonic() + 30
        while controller.status()['running'] and time.monotonic() < deadline:
            time.sleep(.1)
        checks['cancellation_complete'] = controller.status()['job']['status'] == 'cancelled'
        checks['cancel_preserved_summary'] = controller.get_summary(ident)['summary'] == result['summary']
        checks['cancel_unloaded_model'] = not listening()
        report = {'ok': all(checks.values()), 'checks': checks,
                'elapsed_seconds': round(time.monotonic() - started, 2),
                'metrics': result['metrics'], 'synthetic_fixture': True}
        if regression_batches:
            report['first_job'] = first_job
            (SOURCE / 'logs/summary-regression-result.json').write_text(json.dumps(report), encoding='utf-8')
        # Windows can release a killed model's mapped DLL handles just after process exit.
        # Retry only this verified synthetic directory; never mask a failed smoke check.
        deadline = time.monotonic() + 10
        while root.exists():
            try:
                shutil.rmtree(root)
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.2)
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--installed', type=Path, required=True)
    parser.add_argument('--regression-batches', action='store_true')
    args = parser.parse_args()
    report = verify(args.installed.resolve(), args.regression_batches)
    print(json.dumps(report))
    raise SystemExit(0 if report['ok'] else 1)
