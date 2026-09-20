"""Explicit, local transcript summaries. Originals and native compaction are untouched."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import uuid

from desktop_proxy_control import atomic_write
from local_summary_engine import (job_lock, isolated_environment, _windows_job,
                                 SummaryJobError, failure_details, MODEL_REQUEST_TIMEOUT)

ROOT = Path(__file__).resolve().parent
MAX_LINE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_SEGMENT_CHARS = 4000
MAX_BATCH_BYTES = 20000
MAX_STATE_BYTES = 8 * 1024 * 1024
SUMMARY_VERSION = 2
TASK_ID = re.compile(r'^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$')
ACTIVE = {'queued', 'running', 'cancelling'}


def _read(path, default=None):
    try:
        with path.open('rb') as stream:
            data = stream.read(MAX_STATE_BYTES + 1)
        if len(data) > MAX_STATE_BYTES:
            raise ValueError('Local summary state exceeds the limit.')
        return json.loads(data)
    except FileNotFoundError:
        return default


def _write(path, value):
    data = json.dumps(value, ensure_ascii=False).encode('utf-8')
    if len(data) > MAX_STATE_BYTES:
        raise ValueError('Local summary state exceeds the limit; previous checkpoint retained.')
    # Windows cannot replace a checkpoint while a dashboard reader holds it open.
    # Keep atomic publication, allowing only a short sharing-violation retry.
    for attempt in range(50):
        try:
            atomic_write(path, data)
            return
        except PermissionError:
            if attempt == 49:
                raise
            time.sleep(.02)


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

    def lookup_task(self, task_id):
        """Resolve an explicit local task independently of the recent-task picker."""
        task_id = self._id(task_id)
        matches = [p for p in self._files() if p.name.endswith(task_id + '.jsonl')]
        if not matches:
            raise FileNotFoundError('This task is not available in this device\'s local Codex history.')
        if len(matches) != 1:
            raise LookupError('More than one local history file matches this task.')
        path = matches[0]
        with path.open('rb') as stream:
            meta = json.loads(stream.readline(65536))
        if meta.get('type') != 'session_meta' or meta.get('payload', {}).get('id') != task_id:
            raise ValueError('The local task metadata does not match this link.')
        project = str(meta['payload'].get('cwd', '')).replace('\\', '/').rstrip('/').split('/')[-1]
        stat = path.stat()
        value = {'task_id': task_id, 'project': project, 'title': project or task_id,
                 'updated_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                 'bytes': stat.st_size, 'has_summary': self._saved_path(task_id).is_file()}
        # Reuse the existing read-only title lookup; it never selects transcript content.
        from summary_reminders import SummaryReminders
        SummaryReminders(self.root, self.home)._titles([value])
        return value

    def _read_rollout(self, path, task_id, *, on_progress=None):
        messages, calls = [], {}
        result = {'messages': messages, 'source_truncated': False, 'source_incomplete': False,
                  'skipped_lines': 0, 'oversized_lines': 0, 'malformed_lines': 0,
                  'incomplete_tool_pairs': 0}
        # Bound individual JSON allocations, not how much history can be scanned.
        record_limit = 16 * 1024 * 1024
        snapshot_bytes = Path(path).stat().st_size
        total = progress_bytes = records = 0
        line = bytearray()
        oversized = False

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
            while total < snapshot_bytes:
                chunk = source.readline(min(MAX_LINE_BYTES + 1, 1024 * 1024, snapshot_bytes - total))
                if not chunk:
                    result['source_incomplete'] = True
                    break
                total += len(chunk)
                if not oversized:
                    if len(line) + len(chunk) > record_limit:
                        oversized = True
                        line.clear()
                    else:
                        line.extend(chunk)
                complete = chunk.endswith(b'\n')
                records += int(complete)
                if on_progress and (total - progress_bytes >= 1024 * 1024 or
                                    (complete and records % 128 == 0)):
                    on_progress(total, snapshot_bytes)
                    progress_bytes = total
                if not complete:
                    continue
                if oversized:
                    result['source_truncated'] = True
                    result['skipped_lines'] += 1
                    result['oversized_lines'] += 1
                    oversized = False
                    continue
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
                    if (kind == 'message' and payload.get('role') in {'user', 'assistant'}
                            and payload.get('phase') != 'analysis' and payload.get('channel') != 'analysis'):
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
                except (ValueError, TypeError, AttributeError, RecursionError):
                    result['skipped_lines'] += 1
                    result['malformed_lines'] += 1
                    result['source_truncated'] = True
                finally:
                    line.clear()
        if line or oversized:
            result['source_incomplete'] = True
        if on_progress and progress_bytes != total:
            on_progress(total, snapshot_bytes)
        result['incomplete_tool_pairs'] = len(calls)
        return result

    def get_summary(self, task_id):
        task_id = self._id(task_id)
        parsed = self._read_rollout(self._path(task_id), task_id)
        saved = _read(self._saved_path(task_id), {})
        ids = [m['id'] for m in parsed['messages']]
        covered = saved.get('covered_ids', [])
        matches = saved.get('format_version') == SUMMARY_VERSION and ids[:len(covered)] == covered
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
        if getattr(self, '_engine_process', None) is None:
            command = [str(self._runtime('langmem')),
                       str(self.root / 'local_summary_engine.py'), '--session']
            self._engine_process = subprocess.Popen(command, cwd=self.root, env=isolated_environment(),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self._engine_close_job = lambda: None
            self._engine_close_job = _windows_job(self._engine_process)
            self._engine_replies = queue.Queue()
            process, replies = self._engine_process, self._engine_replies
            def read_replies():
                try:
                    while True:
                        line = process.stdout.readline(2 * 1024 * 1024 + 1)
                        if not line or len(line) > 2 * 1024 * 1024:
                            break
                        replies.put(line)
                finally:
                    replies.put(None)
            self._engine_reader = threading.Thread(target=read_replies, daemon=True)
            self._engine_reader.start()
        process = self._engine_process
        data = json.dumps(request, ensure_ascii=False).encode('utf-8') + b'\n'
        if len(data) > 2 * 1024 * 1024:
            raise ValueError('Local summary request exceeds the limit.')
        process.stdin.write(data)
        process.stdin.flush()
        deadline = time.monotonic() + 4 * MODEL_REQUEST_TIMEOUT + 180
        while True:
            if self._cancelled(job_id):
                raise RuntimeError('Summary cancelled.')
            if time.monotonic() > deadline:
                raise SummaryJobError('model_timeout')
            self._update_job(job_id)
            try:
                output = self._engine_replies.get(timeout=1)
            except queue.Empty:
                continue
            if output is None:
                raise SummaryJobError('engine_stopped')
            return json.loads(output)

    def _close_engine(self):
        process = getattr(self, '_engine_process', None)
        if process is None:
            return
        try:
            try:
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(5)
        finally:
            self._engine_close_job()
            reader = getattr(self, '_engine_reader', None)
            if reader:
                reader.join(timeout=1)
            process.stdout.close()
            self._engine_process = None

    def _run_job(self, task_id, job_id):
        with job_lock(self.state / 'worker.lock'):
            terminal, failure, details = 'failed', None, {}
            stage = 'reading'
            recoveries = 0
            try:
                if self._cancelled(job_id):
                    terminal = 'cancelled'
                    return
                self._update_job(job_id, status='running', phase='reading', batches_completed=0, recoveries=0)
                def progress(scanned, total):
                    if self._cancelled(job_id):
                        raise RuntimeError('Summary cancelled.')
                    self._update_job(job_id, scanned_bytes=scanned, snapshot_bytes=total)
                parsed = self._read_rollout(self._path(task_id), task_id, on_progress=progress)
                messages = parsed['messages']
                saved = _read(self._saved_path(task_id), {})
                covered = saved.get('covered_ids', [])
                if (saved.get('format_version') != SUMMARY_VERSION or
                        [m['id'] for m in messages[:len(covered)]] != covered):
                    covered, saved = [], {}
                incomplete = (parsed['source_truncated'] or parsed['source_incomplete'] or
                              parsed['incomplete_tool_pairs'])
                self._update_job(job_id, phase='summarizing', processed_messages=len(covered),
                                 total_messages=len(messages))
                if len(covered) == len(messages):
                    terminal = 'partial' if incomplete else 'unchanged'
                    return
                batches = 0
                while len(covered) < len(messages):
                    if self._cancelled(job_id):
                        terminal = 'cancelled'
                        return
                    pending, size = [], 0
                    for message in messages[len(covered):]:
                        count = len(json.dumps(message, ensure_ascii=False).encode('utf-8'))
                        if size + count > MAX_BATCH_BYTES:
                            break
                        pending.append(message)
                        size += count
                    if not pending:
                        raise RuntimeError('A source segment exceeds the local batch limit.')
                    request = {'messages': pending, 'max_summary_tokens': 1024}
                    if saved.get('running_summary'):
                        request['previous_summary'] = saved['running_summary']
                    stage = 'model'
                    for attempt in range(2):
                        if self._cancelled(job_id):
                            terminal = 'cancelled'
                            return
                        self._update_job(job_id, phase='summarizing')
                        try:
                            value = self._engine(request, task_id, job_id)
                        except Exception as exc:
                            value = {'status': 'failed', **failure_details(exc)}
                        if value.get('status') != 'failed':
                            break
                        error = SummaryJobError(value.get('error_code', 'model_error'),
                                                value.get('error_stage', 'model'), value.get('error_type'))
                        if attempt or not failure_details(error)['retryable'] or self._cancelled(job_id):
                            raise error
                        # Retry only this unsaved local batch, using a fresh owned model
                        # and less input. No external Codex requests are replayed.
                        self._close_engine()
                        pending = pending[:max(1, len(pending) // 2)]
                        request = {**request, 'messages': pending}
                        recoveries += 1
                        self._update_job(job_id, phase='retrying', recoveries=recoveries,
                                         notice='Retrying the unsaved batch with less input after a local model interruption.')
                    running = value.get('running_summary')
                    if value.get('status') == 'failed' or not isinstance(running, dict) or not value.get('summary'):
                        raise SummaryJobError('invalid_summary')
                    returned = set(running.get('summarized_message_ids', []))
                    allowed = covered + [m['id'] for m in pending]
                    if not returned.issubset(set(allowed)) or not set(covered).issubset(returned):
                        raise SummaryJobError('invalid_summary')
                    count = 0
                    for ident in allowed:
                        if ident not in returned:
                            break
                        count += 1
                    if set(allowed[:count]) != returned or count <= len(covered):
                        raise SummaryJobError('invalid_summary')
                    status = ('summarized' if count == len(messages) and not incomplete else 'partial')
                    source_tokens = saved.get('metrics', {}).get('source_tokens', 0) + value.get('processed_input_tokens', value.get('input_tokens', 0))
                    output_tokens = value.get('output_tokens', 0)
                    summary_path = self._saved_path(task_id)
                    summary = {'format_version': SUMMARY_VERSION, 'task_id': task_id, 'status': status,
                        'summary': value['summary'], 'running_summary': running, 'covered_ids': allowed[:count],
                        'updated_at': datetime.now(timezone.utc).isoformat(),
                        'metrics': {'source_tokens': source_tokens, 'summary_tokens': output_tokens,
                                    'estimated_size_reduction': source_tokens - output_tokens}}
                    # Each completed batch is a resumable checkpoint. Cancel wins
                    # against publishing the in-flight batch, not earlier checkpoints.
                    stage = 'publishing'
                    with _control_lock(self.state / 'control.lock'):
                        job = _read(self.job_path, {})
                        if job.get('job_id') != job_id:
                            raise RuntimeError('The summary job was superseded.')
                        if self._cancelled(job_id):
                            terminal = 'cancelled'
                            return
                        _write(summary_path, summary)
                        batches += 1
                        job.update(status='running', heartbeat=time.time(), batches_completed=batches,
                                   processed_messages=count, total_messages=len(messages))
                        _write(self.job_path, job)
                    saved, covered = summary, allowed[:count]
                terminal = status
            except Exception as exc:
                terminal = 'cancelled' if self._cancelled(job_id) else 'failed'
                details = failure_details(exc, stage) if terminal == 'failed' else {}
                failure = details.pop('error', None)
            finally:
                cleanup_failed = False
                try:
                    self._update_job(job_id, phase='unloading')
                finally:
                    try:
                        self._close_engine()
                    except Exception as exc:
                        cleanup_failed = True
                        terminal = 'failed'
                        details = failure_details(SummaryJobError('cleanup_failed', 'cleanup'))
                        failure = details.pop('error')
                        raise
                    finally:
                        if not cleanup_failed and self._cancelled(job_id):
                            terminal = 'cancelled'
                        self._update_job(job_id, status=terminal, phase='complete', error=failure, **details)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', required=True)
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--codex-home', required=True)
    args = parser.parse_args()
    LocalSummaries(ROOT, args.codex_home)._run_job(args.worker, args.job_id)
