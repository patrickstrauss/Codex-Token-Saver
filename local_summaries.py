"""Explicit, local transcript summaries. Originals and native compaction are untouched."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from desktop_proxy_control import atomic_write
from local_summary_engine import job_lock, isolated_environment, _windows_job

ROOT = Path(__file__).resolve().parent
MAX_LINE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_SEGMENT_CHARS = 4000
MAX_BATCH_BYTES = 20000
TASK_ID = re.compile(r'^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$')
ACTIVE = {'queued', 'running', 'cancelling'}


def _read(path, default=None):
    try:
        with path.open('rb') as stream:
            data = stream.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError('Local summary state exceeds the limit.')
        return json.loads(data)
    except FileNotFoundError:
        return default


def _write(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False).encode('utf-8'))


@contextmanager
def _control_lock(path):
    for attempt in range(100):
        guard = job_lock(path)
        try:
            guard.__enter__()
            break
        except RuntimeError:
            if attempt == 99:
                raise
            time.sleep(.01)
    try:
        yield
    finally:
        guard.__exit__(None, None, None)


class LocalSummaries:
    def __init__(self, root=ROOT, codex_home=None):
        self.root = Path(root).resolve()
        self.home = Path(codex_home or os.environ.get('CODEX_HOME') or Path.home() / '.codex').resolve()
        self.state = self.root / 'local-compaction/state'
        self.job_path = self.state / 'job.json'

    @staticmethod
    def _id(task_id):
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id.lower()):
            raise ValueError('Select an explicit local task ID.')
        return task_id.lower()

    def _files(self):
        sessions = self.home / 'sessions'
        if not sessions.is_dir():
            return []
        # ponytail: scan local filenames only; a session index can replace this if catalogs grow slow.
        return [p for p in sessions.rglob('rollout-*.jsonl')
                if p.is_file() and p.resolve().is_relative_to(sessions.resolve())]

    def _path(self, task_id):
        task_id = self._id(task_id)
        matches = [p for p in self._files() if p.name.endswith(task_id + '.jsonl')]
        if len(matches) != 1:
            raise LookupError('The selected local task is missing or ambiguous.')
        return matches[0]

    def _saved_path(self, task_id):
        return self.state / self._id(task_id) / 'summary.json'

    def _preferences(self):
        from bundle_preferences import load_preferences
        return load_preferences(self.root)

    def status(self):
        required = ('local-compaction/.venv/Scripts/python.exe',
                    'local-compaction/model.json', 'local_summary_engine.py')
        available = all((self.root / name).is_file() for name in required)
        runtime_available = False
        try:
            config = _read(self.root / 'local-compaction/model.json', {})
            model = Path(config.get('model_path', ''))
            runtime_available = (model.is_absolute() and model.suffix.lower() == '.gguf' and model.is_file()
                                 and self._runtime('llama_cpp').is_file())
            available = available and self._runtime('langmem').is_file() and runtime_available
        except (ValueError, TypeError, OSError):
            available = False
        job = _read(self.job_path)
        if job and job.get('status') in ACTIVE and time.time() - job.get('heartbeat', 0) > 90:
            job = {**job, 'status': 'interrupted', 'error': 'Worker stopped reporting; refresh may be retried.'}
        prefs = self._preferences()
        return {'available': available, 'runtime_available': runtime_available, 'enabled': prefs['local_summaries'],
                'model_enabled': prefs['llama_cpp'], 'running': bool(job and job.get('status') in ACTIVE),
                'job': job, 'native_compaction_retained': True,
                'reason': None if available else 'Install the local summary runtime and select a local GGUF model.'}

    def _runtime(self, name):
        from component_runtime import runtime_path
        return runtime_path(self.root, name)

    def list_tasks(self, limit=20):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('Task limit must be between 1 and 100.')
        result = []
        for path in sorted(self._files(), key=lambda p: p.stat().st_mtime, reverse=True):
            task_id = path.stem[-36:].lower()
            if not TASK_ID.fullmatch(task_id):
                continue
            try:
                with path.open('rb') as source:
                    meta = json.loads(source.readline(65536))
                if meta.get('type') != 'session_meta' or meta.get('payload', {}).get('id') != task_id:
                    continue
                project = str(meta['payload'].get('cwd', '')).replace('\\', '/').rstrip('/').split('/')[-1]
                stat = path.stat()
                result.append({'task_id': task_id, 'project': project,
                    'updated_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    'bytes': stat.st_size, 'has_summary': self._saved_path(task_id).is_file()})
            except (OSError, ValueError, TypeError):
                continue
            if len(result) >= limit:
                break
        return result

    def _read_rollout(self, path, task_id):
        messages, calls = [], {}
        result = {'messages': messages, 'source_truncated': False, 'source_incomplete': False,
                  'skipped_lines': 0, 'incomplete_tool_pairs': 0}
        total = 0

        def add(role, content):
            if not content:
                return
            parts = [content[i:i + MAX_SEGMENT_CHARS] for i in range(0, len(content), MAX_SEGMENT_CHARS)]
            for index, part in enumerate(parts):
                label = f'[Part {index + 1}/{len(parts)}]\n' if len(parts) > 1 else ''
                value = label + part
                ident = hashlib.sha256(f'{len(messages)}\0{role}\0{value}'.encode()).hexdigest()
                messages.append({'id': ident, 'role': role, 'content': value})

        with Path(path).open('rb') as source:
            while True:
                line = source.readline(MAX_LINE_BYTES + 1)
                if not line:
                    break
                total += len(line)
                if total > MAX_SOURCE_BYTES:
                    result['source_truncated'] = True
                    break
                if len(line) > MAX_LINE_BYTES:
                    result['source_truncated'] = True
                    result['skipped_lines'] += 1
                    while line and not line.endswith(b'\n'):
                        line = source.readline(MAX_LINE_BYTES + 1)
                        total += len(line)
                        if total > MAX_SOURCE_BYTES:
                            return result
                    continue
                if not line.endswith(b'\n'):
                    result['source_incomplete'] = True
                    break
                try:
                    row = json.loads(line)
                    payload = row.get('payload', {})
                    if row.get('type') == 'session_meta':
                        if payload.get('id') != task_id:
                            raise LookupError('Task metadata does not match the selected task.')
                        continue
                    if row.get('type') != 'response_item' or not isinstance(payload, dict):
                        continue
                    kind = payload.get('type')
                    if kind == 'message' and payload.get('role') in {'user', 'assistant'} and payload.get('phase') != 'analysis':
                        chunks = payload.get('content', [])
                        if isinstance(chunks, list):
                            add(payload['role'], '\n'.join(x['text'] for x in chunks
                                if isinstance(x, dict) and isinstance(x.get('text'), str)))
                    elif kind in {'function_call', 'custom_tool_call'}:
                        calls[payload.get('call_id')] = str(payload.get('name', 'tool'))[:100]
                    elif kind in {'function_call_output', 'custom_tool_call_output'}:
                        name = calls.pop(payload.get('call_id'), None)
                        if name:
                            output = payload.get('output', '')
                            if not isinstance(output, str):
                                output = json.dumps(output, ensure_ascii=False)
                            add('tool', f'[Tool result: {name}]\n{output}')
                except (ValueError, TypeError, AttributeError):
                    result['skipped_lines'] += 1
                    result['source_truncated'] = True
        result['incomplete_tool_pairs'] = len(calls)
        return result

    def get_summary(self, task_id):
        task_id = self._id(task_id)
        parsed = self._read_rollout(self._path(task_id), task_id)
        saved = _read(self._saved_path(task_id), {})
        ids = [m['id'] for m in parsed['messages']]
        covered = saved.get('covered_ids', [])
        matches = ids[:len(covered)] == covered
        count = len(covered) if matches else 0
        status = 'stale' if saved and not matches else saved.get('status', 'not_started')
        if saved and matches:
            status = ('partial' if count < len(ids) or parsed['source_truncated'] or
                      parsed['source_incomplete'] or parsed['incomplete_tool_pairs'] else 'summarized')
        return {'task_id': task_id, 'status': status,
                'summary': saved.get('summary'), 'updated_at': saved.get('updated_at'),
                'coverage': {'summarized_messages': count, 'total_messages': len(ids),
                    'pending_messages': len(ids) - count, **{k: v for k, v in parsed.items() if k != 'messages'}},
                'metrics': saved.get('metrics', {}), 'native_compaction_retained': True,
                'measurement': 'Local summary size only; not actual Codex token or quota savings.'}

    def start(self, task_id):
        task_id = self._id(task_id)
        self._path(task_id)
        with _control_lock(self.state / 'control.lock'):
            status = self.status()
            if status['running']:
                raise RuntimeError('Another local summary job is active.')
            if not status['available']:
                raise RuntimeError(status['reason'])
            if not status['enabled'] or not status['model_enabled']:
                raise RuntimeError('Enable local summaries and llama.cpp before refreshing.')
            # Check the owned worker's actual lock as well as its heartbeat.
            with job_lock(self.state / 'worker.lock'):
                job = {'job_id': str(uuid.uuid4()), 'task_id': task_id, 'status': 'queued',
                       'heartbeat': time.time(), 'cancel_requested': False}
                _write(self.job_path, job)
            try:
                job['worker_pid'] = self._launch_worker(task_id, job['job_id'])
                _write(self.job_path, job)
            except Exception:
                _write(self.job_path, {**job, 'status': 'failed', 'error': 'Could not start the local worker.'})
                raise
        return job

    def cancel(self, task_id):
        task_id = self._id(task_id)
        with _control_lock(self.state / 'control.lock'):
            job = _read(self.job_path, {})
            if job.get('task_id') != task_id:
                raise LookupError('This task has no active local summary job.')
            if job.get('status') in ACTIVE:
                job.update(cancel_requested=True, status='cancelling', heartbeat=time.time())
                _write(self.job_path, job)
        return job

    def _launch_worker(self, task_id, job_id):
        command = [sys.executable, str(self.root / 'local_summaries.py'), '--worker', task_id,
                   '--job-id', job_id, '--codex-home', str(self.home)]
        return subprocess.Popen(command, cwd=self.root, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).pid

    def _update_job(self, job_id, **changes):
        with _control_lock(self.state / 'control.lock'):
            job = _read(self.job_path, {})
            if job.get('job_id') != job_id:
                raise RuntimeError('The summary job was superseded.')
            job.update(changes, heartbeat=time.time())
            _write(self.job_path, job)
            return job

    def _cancelled(self, job_id):
        job = _read(self.job_path, {})
        prefs = self._preferences()
        return (job.get('job_id') != job_id or job.get('cancel_requested') or
                not prefs['local_summaries'] or not prefs['llama_cpp'])

    def _engine(self, request, task_id, job_id):
        command = [str(self._runtime('langmem')),
                   str(self.root / 'local_summary_engine.py')]
        process = subprocess.Popen(command, cwd=self.root, env=isolated_environment(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        close_job = lambda: None
        try:
            close_job = _windows_job(process)
            data = json.dumps(request, ensure_ascii=False).encode('utf-8')
            deadline = time.monotonic() + 900
            while True:
                if self._cancelled(job_id):
                    raise RuntimeError('Summary cancelled.')
                if time.monotonic() > deadline:
                    raise TimeoutError('Local summary timed out.')
                self._update_job(job_id)
                try:
                    output, _ = process.communicate(input=data, timeout=1)
                    if process.returncode or len(output) > 2 * 1024 * 1024:
                        raise RuntimeError('Local summary engine failed.')
                    return json.loads(output)
                except subprocess.TimeoutExpired:
                    data = None
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(5)
            close_job()

    def _run_job(self, task_id, job_id):
        with job_lock(self.state / 'worker.lock'):
            try:
                if self._cancelled(job_id):
                    self._update_job(job_id, status='cancelled')
                    return
                self._update_job(job_id, status='running')
                parsed = self._read_rollout(self._path(task_id), task_id)
                messages = parsed['messages']
                saved = _read(self._saved_path(task_id), {})
                covered = saved.get('covered_ids', [])
                if [m['id'] for m in messages[:len(covered)]] != covered:
                    covered, saved = [], {}
                pending, size = [], 0
                for message in messages[len(covered):]:
                    count = len(json.dumps(message, ensure_ascii=False).encode('utf-8'))
                    if size + count > MAX_BATCH_BYTES:
                        break
                    pending.append(message)
                    size += count
                if not pending:
                    self._update_job(job_id, status='unchanged')
                    return
                request = {'messages': pending, 'max_summary_tokens': 1024}
                if saved.get('running_summary'):
                    request['previous_summary'] = saved['running_summary']
                value = self._engine(request, task_id, job_id)
                if self._cancelled(job_id):
                    self._update_job(job_id, status='cancelled')
                    return
                running = value.get('running_summary')
                if value.get('status') == 'failed' or not isinstance(running, dict) or not value.get('summary'):
                    raise RuntimeError('The local model returned no usable summary.')
                returned = set(running.get('summarized_message_ids', []))
                allowed = covered + [m['id'] for m in pending]
                if not returned.issubset(set(allowed)) or not set(covered).issubset(returned):
                    raise RuntimeError('Summary coverage is inconsistent.')
                count = 0
                for ident in allowed:
                    if ident not in returned:
                        break
                    count += 1
                if set(allowed[:count]) != returned or count <= len(covered):
                    raise RuntimeError('Summary did not cover a complete new message prefix.')
                status = ('summarized' if count == len(messages) and not parsed['source_truncated'] and
                          not parsed['source_incomplete'] and not parsed['incomplete_tool_pairs'] else 'partial')
                source_tokens = saved.get('metrics', {}).get('source_tokens', 0) + value.get('processed_input_tokens', value.get('input_tokens', 0))
                output_tokens = value.get('output_tokens', 0)
                summary_path = self._saved_path(task_id)
                summary = {'task_id': task_id, 'status': status,
                    'summary': value['summary'], 'running_summary': running, 'covered_ids': allowed[:count],
                    'updated_at': datetime.now(timezone.utc).isoformat(),
                    'metrics': {'source_tokens': source_tokens, 'summary_tokens': output_tokens,
                                'estimated_size_reduction': source_tokens - output_tokens}}
                # Linearize cancellation and publication: Cancel either precedes this
                # transaction (no artifact change) or follows an already finished job.
                with _control_lock(self.state / 'control.lock'):
                    job = _read(self.job_path, {})
                    if job.get('job_id') != job_id:
                        raise RuntimeError('The summary job was superseded.')
                    if self._cancelled(job_id):
                        job.update(status='cancelled', heartbeat=time.time())
                    else:
                        _write(summary_path, summary)
                        job.update(status=status, heartbeat=time.time())
                    _write(self.job_path, job)
            except Exception as exc:
                status = 'cancelled' if self._cancelled(job_id) else 'failed'
                self._update_job(job_id, status=status, error=f'Local job {status} ({type(exc).__name__}); originals retained.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', required=True)
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--codex-home', required=True)
    args = parser.parse_args()
    LocalSummaries(ROOT, args.codex_home)._run_job(args.worker, args.job_id)
