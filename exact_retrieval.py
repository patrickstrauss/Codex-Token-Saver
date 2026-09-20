"""Local proof that an exact tool response must not be compressed again.

The receipt authenticates bytes, not instructions. It grants no tool or model
privileges. Only the bundle creates receipts; the proxy never trusts a plain
model-controlled marker or creates a key while validating one.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import tempfile

ROOT = Path(__file__).resolve().parent
_MAX_CHARS = 16 * 1024 * 1024
_RECEIPT = re.compile(r'\A\[Headroom exact v1 chars=([0-9]{1,8}) sha256=([0-9a-f]{64}) mac=([0-9a-f]{64})\]\n')
_EXEC_PREFIX = re.compile(
    r'\AScript (?:completed|running with cell ID [A-Za-z0-9_-]{1,100})\r?\n'
    r'Wall time:? [0-9]{1,8}(?:\.[0-9]{1,8})? seconds\r?\nOutput:\r?\n')


def _key(root, *, create=False):
    path = Path(root) / 'proxy' / 'exact-retrieval.key'
    try:
        value = path.read_bytes()
    except FileNotFoundError:
        if not create:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        # Publish a complete key atomically: concurrent MCP processes either
        # win the link or read the winner. Never overwrite an existing key.
        descriptor, temporary = tempfile.mkstemp(prefix='.exact-key-', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(secrets.token_bytes(32))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
            value = path.read_bytes()
        finally:
            os.unlink(temporary)
    if len(value) != 32:
        raise ValueError('Exact retrieval signing key is invalid')
    return value


def _mac(key, size, digest):
    return hmac.new(key, f'headroom-exact-v1:{size}:{digest}'.encode('ascii'), hashlib.sha256).hexdigest()


def sign_exact_response(text, *, root=ROOT):
    """Prefix an exact response with a receipt, preserving every payload byte."""
    if not isinstance(text, str) or len(text) > _MAX_CHARS:
        raise ValueError('Exact response is invalid or too large')
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    signature = _mac(_key(root, create=True), len(text), digest)
    return f'[Headroom exact v1 chars={len(text)} sha256={digest} mac={signature}]\n{text}'


def exact_response_is_verified(value, *, root=ROOT):
    """Validate a receipt in bounded native/MCP/functions.exec JSON envelopes."""
    try:
        key = _key(root)
    except (OSError, ValueError):
        return False
    if key is None:
        return False
    pending = [(value, 0)]
    visited = 0
    scanned_chars = 0
    while pending and visited < 2048:
        item, depth = pending.pop()
        visited += 1
        if depth > 12:
            continue
        if isinstance(item, str):
            scanned_chars += len(item)
            if len(item) > _MAX_CHARS or scanned_chars > _MAX_CHARS * 4:
                return False
            prefix = _EXEC_PREFIX.match(item)
            if prefix:
                # This is transport metadata, not proof. The remaining raw or
                # JSON-wrapped text must still authenticate with the local key.
                pending.append((item[prefix.end():], depth + 1))
                continue
            match = _RECEIPT.match(item)
            if match:
                size, digest, signature = match.groups()
                content = item[match.end():]
                if len(content) == int(size) and hmac.compare_digest(signature, _mac(key, size, digest)):
                    try:
                        actual = hashlib.sha256(content.encode('utf-8')).hexdigest()
                    except UnicodeError:
                        continue
                    if hmac.compare_digest(digest, actual):
                        return True
            stripped = item.lstrip()
            if stripped.startswith(('{', '[', '"')):
                # functions.exec may emit multiple text(JSON) blocks. Decode
                # actual JSON documents; never replace literal escape sequences.
                decoder = json.JSONDecoder()
                remaining = stripped
                for _ in range(32):
                    try:
                        decoded, end = decoder.raw_decode(remaining)
                    except (ValueError, RecursionError):
                        break
                    pending.append((decoded, depth + 1))
                    remaining = remaining[end:].lstrip()
                    if not remaining.startswith(('{', '[', '"')):
                        break
        elif isinstance(item, dict):
            if len(item) > 2048:
                return False
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            if len(item) > 2048:
                return False
            pending.extend((child, depth + 1) for child in item)
    return False
