"""Offline file compression for Codex desktop's optional Headroom MCP tools.

Nothing here changes Codex routing, models, or authentication. Imports of the
Headroom SDK and tokenizer are lazy so MCP initialization needs neither.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import base64
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any, Callable

from exact_retrieval import sign_exact_response
from bundle_preferences import load_preferences
from proxy_retrieval import read_proxy_original
from runtime_selection import activate_headroom_runtime
activate_headroom_runtime(Path(__file__).resolve().parent)


MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_WINDOW_LINES = 10000
ORIGINAL_TTL_SECONDS = 86400
TOKENIZER_NAME = "o200k_base"
# Pinned to the installed tiktoken_ext.openai_public.o200k_base constructor.
# We load verified local bytes directly: tiktoken's ordinary loader can fetch
# this URL without a timeout and does not honor HEADROOM_OFFLINE.
O200K_URL = "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"
O200K_SHA256 = "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"
O200K_PATTERN = "|".join(
    [
        r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]*[\p{Ll}\p{Lm}\p{Lo}\p{M}]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
        r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]+[\p{Ll}\p{Lm}\p{Lo}\p{M}]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
        r"\p{N}{1,3}",
        r" ?[^\s\p{L}\p{N}]+[\r\n/]*",
        r"\s*[\r\n]+",
        r"\s+(?!\S)",
        r"\s+",
    ]
)


class LocalTokenizerUnavailable(RuntimeError):
    """The local vocabulary cannot support truthful token estimates."""


def _read_local_tokenizer_file(blobpath: str) -> bytes:
    """Reject every remote fallback inside this dedicated local tool process."""
    if "://" in blobpath or blobpath.startswith("\\\\"):
        raise LocalTokenizerUnavailable(
            "Remote tokenizer loading is disabled. Use a native file read for this request "
            "and repair the bundle's local tokenizer cache. No download was attempted."
        )
    with open(blobpath, "rb", buffering=0) as source:
        return source.read()


class DesktopHeadroom:
    """Read files, return compact overviews, and retain exact originals.

    ``compressor`` and ``token_counter`` optionally accept callables taking one
    string. ``cache`` is a Headroom CompressionStore-compatible test seam.
    Headroom environment settings belong to the calling server, before imports.
    """

    def __init__(
        self,
        state_dir: str | Path,
        compressor: Callable[[str], str] | None = None,
        token_counter: Callable[[str], int] | None = None,
        cache: Any = None,
        bundle_root: str | Path | None = None,
    ):
        self.bundle_root = Path(bundle_root) if bundle_root is not None else Path(__file__).resolve().parent
        self.state_dir = Path(state_dir).resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.activity_path = self.state_dir / "activity.db"
        self._compressor = compressor
        self._token_counter = token_counter
        self._local_encoding = None
        self._cache = cache
        self._lazy_lock = threading.RLock()
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS events ("
                "id INTEGER PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL, "
                "input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, "
                "saved_tokens INTEGER NOT NULL)"
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.activity_path, timeout=10)
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _count(self, text: str) -> int:
        with self._lazy_lock:
            if self._token_counter is None:
                encoding = self._load_local_encoding()
                self._token_counter = lambda value: len(encoding.encode(value, disallowed_special=()))
            count = self._token_counter(text)
        if not isinstance(count, int) or count < 0:
            raise ValueError("Token counter must return a nonnegative integer.")
        return count

    def _load_local_encoding(self):
        with self._lazy_lock:
            if self._local_encoding is not None:
                return self._local_encoding
            cache_dir = os.environ.get("TIKTOKEN_CACHE_DIR")
            cache_root = Path(cache_dir) if cache_dir else Path(__file__).resolve().parent / "headroom" / "tokenizer-cache"
            cache_path = cache_root / hashlib.sha1(O200K_URL.encode()).hexdigest()
            error_message = (
                "Local o200k_base tokenizer cache is missing, unreadable, or corrupt. "
                "Use a native file read for this request and repair the bundle's tokenizer cache. "
                "No vocabulary download was attempted."
            )
            try:
                with cache_path.open("rb") as source:
                    data = source.read(8 * 1024 * 1024 + 1)
            except OSError as error:
                raise LocalTokenizerUnavailable(error_message) from error
            if hashlib.sha256(data).hexdigest() != O200K_SHA256:
                raise LocalTokenizerUnavailable(error_message)
            # The hash covers both the vocabulary and rank order. Parsing these
            # already-read bytes avoids a check/reopen/download race entirely.
            ranks = {
                base64.b64decode(token, validate=True): int(rank)
                for token, rank in (line.split() for line in data.splitlines() if line)
            }
            token_module = importlib.import_module("tiktoken")
            # The SDK's transforms might ask for another encoding. Retain
            # ordinary local-file loading while refusing its network fallback,
            # without touching sockets (stdio's asyncio loop needs socketpair).
            importlib.import_module("tiktoken.load").read_file = _read_local_tokenizer_file
            encoding = token_module.Encoding(
                name=TOKENIZER_NAME,
                pat_str=O200K_PATTERN,
                mergeable_ranks=ranks,
                special_tokens={"<|endoftext|>": 199999, "<|endofprompt|>": 200018},
            )
            # Headroom also calls tiktoken.get_encoding for gpt-4o. Publish this
            # validated encoding in the pinned dependency's process-local cache
            # so that SDK token counting cannot trigger its remote constructor.
            registry = importlib.import_module("tiktoken.registry")
            with registry._lock:
                registry.ENCODINGS[TOKENIZER_NAME] = encoding
            self._local_encoding = encoding
            return encoding

    def _compress(self, text: str) -> str:
        with self._lazy_lock:
            if self._compressor is not None:
                compressed = self._compressor(text)
            else:
                self._load_local_encoding()
                sdk = importlib.import_module("headroom")
                result = sdk.compress(
                    [{"role": "tool", "content": text}],
                    # This selects local tokenization only. No LLM request is made.
                    model="gpt-4o",
                    protect_recent=0,
                    kompress_model="disabled",
                    protect_analysis_context=True,
                    compress_system_messages=False,
                )
                if text and result.tokens_before <= 0:
                    raise RuntimeError("Headroom did not return compression measurements.")
                compressed = result.messages[0].get("content")
        if not isinstance(compressed, str) or (text and not compressed.strip()):
            raise ValueError("Headroom returned an empty or non-text result.")
        return compressed

    def _get_cache(self):
        with self._lazy_lock:
            if self._cache is None:
                store_module = importlib.import_module("headroom.cache.compression_store")
                sqlite_module = importlib.import_module("headroom.cache.backends.sqlite")
                self._cache = store_module.CompressionStore(
                    default_ttl=ORIGINAL_TTL_SECONDS,
                    enable_feedback=False,
                    backend=sqlite_module.SQLiteBackend(self.state_dir / "originals.db"),
                )
            return self._cache

    @staticmethod
    def _window(text: str, start_line: int, max_lines: int) -> tuple[str, int, int]:
        if type(start_line) is not int or start_line <= 0:
            raise ValueError("start_line must be a positive integer.")
        if type(max_lines) is not int or not 1 <= max_lines <= MAX_WINDOW_LINES:
            raise ValueError(f"max_lines must be between 1 and {MAX_WINDOW_LINES}.")
        lines = text.splitlines(keepends=True)
        if start_line > max(len(lines), 1):
            raise ValueError(f"start_line exceeds the file's {len(lines)} lines.")
        selected = lines[start_line - 1 : start_line - 1 + max_lines]
        last_line = start_line + len(selected) - 1
        return "".join(selected), len(lines), last_line

    @staticmethod
    def _read_utf8(path: str | Path) -> tuple[Path, str]:
        resolved = Path(path)
        if not resolved.is_absolute():
            raise ValueError("An absolute file path is required.")
        resolved = resolved.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError("The path must identify a regular file.")
        if resolved.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Files larger than 2 MiB are not supported; use a targeted native read.")
        # Bound the read even if the file grows after stat(). Reading bytes and
        # strict decoding preserve CRLF, lone CR, BOM, and a missing final newline.
        with resolved.open("rb") as source:
            raw = source.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError("Files larger than 2 MiB are not supported; use a targeted native read.")
        if b"\x00" in raw:
            raise ValueError("Binary files containing NUL bytes are not supported.")
        try:
            return resolved, raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Only UTF-8 text files are supported.") from error

    @staticmethod
    def _raw_response(
        source: str, content: str, start_line: int, last_line: int, total_lines: int, notice: str = ""
    ) -> str:
        header = f"Exact text: {source}\nLines {start_line}-{last_line} of {total_lines}."
        if notice:
            header += f"\n{notice}"
        return sign_exact_response(f"{header}\n\n{content}")

    @staticmethod
    def _overview_response(
        source: str, content: str, content_hash: str, start_line: int, last_line: int, total_lines: int
    ) -> str:
        return (
            f"Compressed overview: {source}\n"
            f"Source lines {start_line}-{last_line} of {total_lines}; content_hash={content_hash}.\n"
            "Details or formatting may be omitted. Before exact edits or quotes, call retrieve "
            f"with content_hash={content_hash} and the required line range for the original.\n\n"
            f"{content}"
        )

    def _record(self, kind: str, input_tokens: int, output_tokens: int) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT INTO events(ts,kind,input_tokens,output_tokens,saved_tokens) VALUES(?,?,?,?,?)",
                (timestamp, kind, input_tokens, output_tokens, input_tokens - output_tokens),
            )
            connection.commit()

    def read_file(
        self, path: str, start_line: int = 1, max_lines: int = 1200, compress: bool = True
    ) -> str:
        """Return a file window, compressed only when useful and recoverable."""
        if type(compress) is not bool:
            raise ValueError("compress must be a boolean.")
        resolved, original = self._read_utf8(path)
        selected, total_lines, last_line = self._window(original, start_line, max_lines)
        source = json.dumps(str(resolved), ensure_ascii=False)
        if not load_preferences(self.bundle_root)['headroom_local']:
            return self._raw_response(source, selected, start_line, last_line, total_lines,
                                      'Local Headroom is off; returning original text.')
        input_tokens = self._count(selected)
        response = self._raw_response(source, selected, start_line, last_line, total_lines)
        if compress and selected:
            try:
                compressed = self._compress(selected)
                key = hashlib.sha256(original.encode("utf-8")).hexdigest()[:24]
                candidate = self._overview_response(source, compressed, key, start_line, last_line, total_lines)
                if (
                    compressed != selected
                    and self._count(compressed) < input_tokens
                    and self._count(candidate) < self._count(response)
                ):
                    # Store the FULL file even when only one window was read.
                    # Never expose a compact result if its original cannot be kept.
                    stored_key = self._get_cache().store(
                        original=original,
                        compressed=compressed,
                        original_tokens=self._count(original),
                        compressed_tokens=self._count(compressed),
                        tool_name="headroom_read_file",
                        compression_strategy="desktop_mcp",
                        ttl=ORIGINAL_TTL_SECONDS,
                        explicit_hash=key,
                    )
                    if stored_key != key:
                        raise RuntimeError("Original content cache returned an unexpected key.")
                    stored = self._get_cache().retrieve(key)
                    if stored is None or stored.original_content != original:
                        raise RuntimeError("Original content cache could not verify the saved text.")
                    response = candidate
            except Exception:
                # Compression and its cache are optional; source text is authoritative.
                response = self._raw_response(
                    source, selected, start_line, last_line, total_lines,
                    "Compression unavailable; returning original text.",
                )
        self._record("read", input_tokens, self._count(response))
        return response

    def retrieve(self, content_hash: str, start_line: int = 1, max_lines: int = 1200) -> str:
        """Retrieve a faithful window from a stored original, including after restart."""
        if not isinstance(content_hash, str) or re.fullmatch(r"(?:[0-9a-fA-F]{12}|[0-9a-fA-F]{24})", content_hash) is None:
            raise ValueError("content_hash must be a 12-character proxy or 24-character local hexadecimal reference.")
        # Validate numeric bounds before accessing the cache.
        self._window("", start_line=1, max_lines=max_lines)
        if type(start_line) is not int or start_line <= 0:
            raise ValueError("start_line must be a positive integer.")
        proxy_reference = len(content_hash) == 12
        if proxy_reference:
            original = read_proxy_original(content_hash.lower())
        else:
            entry = self._get_cache().retrieve(content_hash.lower())
            if entry is None:
                raise LookupError("Original not found or expired. Re-read the source file; do not retry this hash.")
            original = entry.original_content
        selected, total_lines, last_line = self._window(original, start_line, max_lines)
        response = self._raw_response(
            f"stored original {content_hash.lower()}", selected, start_line, last_line, total_lines
        )
        if not proxy_reference:
            self._record("retrieve", 0, self._count(response))
        return response

    def stats(self) -> dict[str, Any]:
        """Return signed token estimates, including headers and original retrievals."""
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(saved_tokens),0), "
                "COALESCE(SUM(CASE WHEN kind IN ('read','command') AND saved_tokens>0 THEN saved_tokens ELSE 0 END),0), "
                "COALESCE(SUM(CASE WHEN kind='retrieve' THEN output_tokens ELSE 0 END),0), "
                "COALESCE(SUM(CASE WHEN kind='read' THEN 1 ELSE 0 END),0), "
                "COALESCE(SUM(CASE WHEN kind='retrieve' THEN 1 ELSE 0 END),0), MAX(ts), "
                "COALESCE(SUM(CASE WHEN kind='command' THEN 1 ELSE 0 END),0), "
                "COALESCE(SUM(CASE WHEN kind='command' THEN saved_tokens ELSE 0 END),0) FROM events"
            ).fetchone()
            attempt_row = (0, None)
            attempt_statuses = {}
            if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='command_attempts'").fetchone():
                attempt_row = connection.execute('SELECT COUNT(*),MAX(ts) FROM command_attempts').fetchone()
                attempt_statuses = dict(connection.execute('SELECT status,COUNT(*) FROM command_attempts GROUP BY status'))
        return dict(
            zip(
                ("total_saved", "gross_saved", "retrieval_tokens", "read_count", "retrieve_count", "last_recorded_at",
                 "command_count", "command_saved"),
                row,
            ),
            estimated=True,
            tokenizer=TOKENIZER_NAME,
            command_attempt_count=attempt_row[0],
            last_command_at=attempt_row[1],
            command_statuses=attempt_statuses,
            note="Local token estimates, including returned metadata and retrievals; not billing or quota measurements.",
        )
