"""Conservative, locally measured compression of successful command stdout."""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sqlite3

from desktop_headroom import DesktopHeadroom, ORIGINAL_TTL_SECONDS

ROOT = Path(__file__).resolve().parent
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
# Medium structured outputs can save tokens too. The final admission check
# still includes the recovery header and requires fewer bytes AND tokens.
# Keep the byte gate in native/RtkLauncher.cs aligned with this value.
MIN_OUTPUT_BYTES = 1024
MIN_OUTPUT_TOKENS = 350


def configure_offline_environment(state_dir: Path) -> None:
    """Use only inside the compression worker, never in the child command."""
    os.environ.update({
        'HEADROOM_WORKSPACE_DIR': str(state_dir), 'HEADROOM_OFFLINE': '1',
        'HEADROOM_TELEMETRY': 'off', 'HEADROOM_LOG_PAYLOAD_PREVIEW': '0',
        'HF_HUB_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1',
        'TRANSFORMERS_OFFLINE': '1', 'LITELLM_LOCAL_MODEL_COST_MAP': 'True',
        'TIKTOKEN_CACHE_DIR': str(ROOT / 'headroom/tokenizer-cache'),
    })


@dataclass
class CompressionResult:
    output: bytes
    status: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    content_hash: str | None = None


class CommandCompressor:
    def __init__(self, state_dir: str | Path, backend: DesktopHeadroom | None = None):
        self.state_dir = Path(state_dir)
        self.backend = backend if backend is not None else DesktopHeadroom(self.state_dir)

    def process(self, original: bytes, return_code: int, exact: bool = False) -> CompressionResult:
        if exact:
            return CompressionResult(original, 'exact_requested')
        if return_code != 0:
            return CompressionResult(original, 'command_failed')
        if len(original) > MAX_OUTPUT_BYTES:
            return CompressionResult(original, 'size_limit')
        if len(original) < MIN_OUTPUT_BYTES:
            return CompressionResult(original, 'small_output')
        if b'\0' in original:
            return CompressionResult(original, 'binary_output')
        try:
            text = original.decode('utf-8')
        except UnicodeDecodeError:
            return CompressionResult(original, 'non_utf8')
        input_tokens = None
        try:
            input_tokens = self.backend._count(text)
            if input_tokens < MIN_OUTPUT_TOKENS:
                return CompressionResult(original, 'small_output', input_tokens, input_tokens)
            compressed = self.backend._compress(text)
            key = hashlib.sha256(original).hexdigest()[:24]
            candidate = (
                '[Headroom: compressed command stdout; exit 0]\n'
                f'content_hash={key}; exact original retained for 24 hours.\n'
                'Details may be omitted. Use headroom_retrieve with this hash and a line range '
                'before precise edits, quotes, or completeness-sensitive decisions.\n\n'
                + compressed
            )
            output_tokens = self.backend._count(candidate)
            if compressed == text or output_tokens >= input_tokens or len(candidate.encode('utf-8')) >= len(original):
                return CompressionResult(original, 'no_reduction', input_tokens, input_tokens)
            cache = self.backend._get_cache()
            stored_key = cache.store(
                original=text, compressed=compressed, original_tokens=input_tokens,
                compressed_tokens=self.backend._count(compressed), tool_name='headroom_run',
                compression_strategy='desktop_command', ttl=ORIGINAL_TTL_SECONDS,
                explicit_hash=key,
            )
            stored = cache.retrieve(key)
            if stored_key != key or stored is None or stored.original_content != text:
                raise RuntimeError('Exact original cache verification failed')
            return CompressionResult(candidate.encode('utf-8'), 'compressed', input_tokens, output_tokens, key)
        except Exception:
            return CompressionResult(original, 'compression_unavailable', input_tokens, input_tokens)

    def record(self, result: CompressionResult, executable: str, return_code: int,
               stdout_bytes: int, stderr_bytes: int) -> None:
        """Record only token estimates we actually measured; receipts carry no argv or output."""
        timestamp = datetime.now(timezone.utc).isoformat()
        with closing(self.backend._connect()) as connection:
            connection.execute(
                'CREATE TABLE IF NOT EXISTS command_attempts ('
                'id INTEGER PRIMARY KEY, ts TEXT NOT NULL, executable TEXT NOT NULL, '
                'status TEXT NOT NULL, return_code INTEGER NOT NULL, '
                'stdout_bytes INTEGER NOT NULL, stderr_bytes INTEGER NOT NULL, '
                'input_tokens INTEGER, output_tokens INTEGER, content_hash TEXT)'
            )
            connection.execute(
                'INSERT INTO command_attempts(ts,executable,status,return_code,stdout_bytes,stderr_bytes,'
                'input_tokens,output_tokens,content_hash) VALUES(?,?,?,?,?,?,?,?,?)',
                (timestamp, Path(executable).name, result.status, return_code, stdout_bytes, stderr_bytes,
                 result.input_tokens, result.output_tokens, result.content_hash),
            )
            if result.input_tokens is not None and result.output_tokens is not None:
                connection.execute(
                    'INSERT INTO events(ts,kind,input_tokens,output_tokens,saved_tokens) VALUES(?,?,?,?,?)',
                    (timestamp, 'command', result.input_tokens, result.output_tokens,
                     result.input_tokens - result.output_tokens),
                )
            connection.commit()
