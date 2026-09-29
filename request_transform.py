"""Bounded, recoverable tool-text transforms. This module cannot dispatch a model request."""
import asyncio
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time

from exact_retrieval import exact_response_is_verified

MAX_BYTES = 8 * 1024 * 1024
TTL_SECONDS = 1800
_ID = re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')
_REFERENCE = re.compile(r'[0-9a-f]{12}\Z')


class OriginalStore:
    """Durable originals, including across pause/restart; never evict an unexpired original."""
    def __init__(self, path, *, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS originals (ref TEXT PRIMARY KEY, text TEXT NOT NULL, expires REAL NOT NULL)')
            db.commit()

    def put(self, text):
        encoded = text.encode('utf-8')
        if len(encoded) > MAX_BYTES:
            raise ValueError('Original exceeds limit')
        ref = hashlib.sha256(encoded).hexdigest()[:12]
        with closing(sqlite3.connect(self.path, timeout=0.1)) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM originals WHERE expires <= ?', (self.clock(),))
            existing = db.execute('SELECT text FROM originals WHERE ref=?', (ref,)).fetchone()
            if existing and existing[0] != text:
                raise ValueError('Original reference collision')
            used = db.execute('SELECT coalesce(sum(length(cast(text AS BLOB))), 0) FROM originals').fetchone()[0]
            if not existing and used + len(encoded) > 128 * 1024 * 1024:
                raise ValueError('Original store is full')
            db.execute('INSERT OR REPLACE INTO originals VALUES (?, ?, ?)', (ref, text, self.clock() + TTL_SECONDS))
            db.commit()
        return ref

    def retrieve(self, ref):
        if not isinstance(ref, str) or not _REFERENCE.fullmatch(ref):
            raise ValueError('Invalid reference')
        with closing(sqlite3.connect(self.path, timeout=0.1)) as db:
            row = db.execute('SELECT text FROM originals WHERE ref=? AND expires>?', (ref, self.clock())).fetchone()
        if not row:
            raise KeyError('Original is unavailable or expired')
        return row[0]


def parse_request(value):
    if not isinstance(value, dict) or set(value) != {'protocol', 'request_id', 'scope_id', 'budget_ms', 'entries'}:
        raise ValueError('Invalid request')
    if type(value['protocol']) is not int or value['protocol'] != 1:
        raise ValueError('Unsupported protocol')
    if any(not isinstance(value[key], str) or not _ID.fullmatch(value[key]) for key in ('request_id', 'scope_id')):
        raise ValueError('Invalid request identity')
    if type(value['budget_ms']) is not int or not 1 <= value['budget_ms'] <= 500:
        raise ValueError('Invalid deadline')
    entries = value['entries']
    if not isinstance(entries, list) or len(entries) > 128:
        raise ValueError('Too many entries')
    seen, total = set(), 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'id', 'original_sha256', 'text'}:
            raise ValueError('Invalid entry')
        if not isinstance(entry['id'], str) or not _ID.fullmatch(entry['id']) or entry['id'] in seen:
            raise ValueError('Invalid entry identity')
        seen.add(entry['id'])
        if not isinstance(entry['text'], str):
            raise ValueError('Only text is supported')
        encoded = entry['text'].encode('utf-8')
        total += len(encoded)
        if total > MAX_BYTES or entry['original_sha256'] != hashlib.sha256(encoded).hexdigest():
            raise ValueError('Invalid entry size or digest')
    return value


def _reply(request_id, outcome, replacements=None, reason=None):
    result = {'protocol': 1, 'request_id': request_id, 'outcome': outcome, 'replacements': replacements or []}
    if reason:
        result['reason'] = reason
    return result


class TransformService:
    def __init__(self, compressor, store, *, root, token_counter, clock=time.monotonic, enabled_reader=None):
        self.compressor, self.store, self.root = compressor, store, Path(root)
        self.token_counter, self.clock = token_counter, clock
        self._enabled, self.ready = True, True
        self._enabled_reader = enabled_reader
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='headroom-transform')
        self._lock = threading.RLock()
        self._active, self._failures, self._open_until = 0, 0, 0.0
        self._cache, self._cache_bytes = OrderedDict(), 0
        self.counts = {key: 0 for key in ('compressed', 'unchanged', 'bypassed', 'error')}

    @property
    def enabled(self):
        try:
            return self._enabled and (self._enabled_reader is None or self._enabled_reader() is True)
        except Exception:
            return False

    @enabled.setter
    def enabled(self, value):
        self._enabled = value is True

    def close(self):
        self.enabled = False
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _work(self, entries, deadline):
        replacements = []
        complete = True
        for entry in entries:
            # Replayed history must not recompress every old output when a new
            # entry arrives. Keep completed work even if its batch times out.
            key = ('entry', entry['original_sha256'])
            result = self._cached(key)
            if result is None:
                if time.monotonic() >= deadline:
                    complete = False
                    continue  # Later cache hits remain useful even after timeout.
                replacement = self._compress_entry(entry)
                result = _reply(None, 'compressed' if replacement else 'unchanged',
                                [replacement] if replacement else [])
                self._remember(key, result)
            replacements.extend(dict(item, id=entry['id']) for item in result['replacements'])
        return replacements, complete

    def _compress_entry(self, entry):
        text = entry['text']
        if (len(text.encode('utf-8')) < 1024 or not text.strip()
                or text.lstrip().startswith(('{', '['))
                or '<<ccr:' in text or '[Headroom request overview v1' in text
                or exact_response_is_verified(text, root=self.root)):
            return None
        compressed = self.compressor(text)
        if not isinstance(compressed, str) or not compressed.strip():
            raise ValueError('Invalid compressor result')
        # SDK CCR state is process-local; expose only our durable reference.
        compressed = re.sub(r'<<ccr:[0-9a-f]{12},[^\r\n]*?>>', '', compressed).strip()
        if not compressed or '<<ccr:' in compressed:
            return None
        ref = hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]
        replacement = f'[Headroom request overview v1; exact original: headroom_retrieve(content_hash="{ref}")]\n{compressed}'
        if (len(replacement.encode('utf-8')) >= len(text.encode('utf-8'))
                or self.token_counter(replacement) >= self.token_counter(text)):
            return None
        if self.store.put(text) != ref or self.store.retrieve(ref) != text:
            raise ValueError('Original could not be retained')
        return {'id': entry['id'], 'original_sha256': entry['original_sha256'],
                'replacement': replacement, 'retrieval_reference': ref}

    def _cached(self, key):
        with self._lock:
            cached = self._cache.get(key)
            if cached is None:
                return None
            if self.clock() - cached[0] < TTL_SECONDS:
                try:
                    for entry in cached[1]['replacements']:
                        self.store.retrieve(entry['retrieval_reference'])
                    self._cache.move_to_end(key)
                    return cached[1]
                except (KeyError, ValueError, sqlite3.Error):
                    pass
            self._cache_bytes -= self._cache.pop(key)[2]
            return None

    def _remember(self, key, result):
        if result['outcome'] not in ('compressed', 'unchanged'):
            return  # A transient bypass must never become a 30-minute decision.
        size = len(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        if size > MAX_BYTES:
            return
        with self._lock:
            if key in self._cache:
                self._cache_bytes -= self._cache.pop(key)[2]
            self._cache[key] = (self.clock(), result, size)
            self._cache_bytes += size
            while len(self._cache) > 512 or self._cache_bytes > 32 * 1024 * 1024:
                self._cache_bytes -= self._cache.popitem(last=False)[1][2]

    def _run_work(self, entries, deadline):
        try:
            return self._work(entries, deadline)
        finally:
            # Release on real worker completion, not an event-loop callback that
            # can be delayed across several immediately completed awaits.
            with self._lock:
                self._active -= 1

    def _consume(self, future):
        # Consume abandoned worker errors without returning private exception text.
        if not future.cancelled():
            future.exception()

    async def transform(self, value):
        try:
            value = parse_request(value)
        except (ValueError, TypeError, RecursionError):
            return _reply(None, 'error', reason='invalid_request')
        request_id = value['request_id']
        deadline = time.monotonic() + value['budget_ms'] / 1000
        # Every request rechecks policy and durable originals before cache reuse.
        with self._lock:
            if not self.enabled or not self.ready:
                return _reply(request_id, 'bypassed', reason='unavailable')
            replacements, complete = self._work(value['entries'], 0)
            if complete:
                return _reply(request_id, 'compressed' if replacements else 'unchanged', replacements)
            if self.clock() < self._open_until:
                return _reply(request_id, 'compressed' if replacements else 'bypassed', replacements, reason='circuit_open')
            if self._active >= 2 or (self._failures >= 3 and self._active):
                return _reply(request_id, 'compressed' if replacements else 'bypassed', replacements, reason='busy')
            self._active += 1
        future = asyncio.get_running_loop().run_in_executor(self._executor, self._run_work, value['entries'], deadline)
        future.add_done_callback(self._consume)
        try:
            replacements, complete = await asyncio.wait_for(asyncio.shield(future), max(.001, deadline - time.monotonic()))
            if not self.enabled:
                return _reply(request_id, 'bypassed', reason='unavailable')
            if not complete:
                raise TimeoutError()
            result = _reply(request_id, 'compressed' if replacements else 'unchanged', replacements)
            if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > MAX_BYTES:
                raise ValueError('Reply exceeds limit')
            with self._lock:
                self._failures, self._open_until = 0, 0.0
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if not self.enabled:
                return _reply(request_id, 'bypassed', reason='unavailable')
            replacements, _ = self._work(value['entries'], 0)
            result = _reply(request_id, 'compressed' if replacements else 'bypassed', replacements,
                            reason='timeout' if isinstance(error, TimeoutError) else 'transform_failed')
            with self._lock:
                self._failures += 1
                if self._failures >= 3:
                    self._open_until = self.clock() + 30
        with self._lock:
            self.counts[result['outcome']] += 1
        return result
