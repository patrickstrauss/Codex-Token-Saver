"""Run an already approved executable once, then optionally reduce successful stdout.

The hook rewrites the command; it does not run it. This runner executes inside the
original shell tool's sandbox. It never invokes another shell or changes routing.
"""
from __future__ import annotations

import base64
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from bundle_preferences import load_preferences

from command_compression import (CommandCompressor, CompressionResult,
                                 MAX_OUTPUT_BYTES, MIN_OUTPUT_BYTES,
                                 configure_offline_environment)

ROOT = Path(__file__).resolve().parent
MAX_BUFFER_SECONDS = 5.0
COMPRESSION_TIMEOUT_SECONDS = 8.0
RECORD_TIMEOUT_SECONDS = 2.0


def write_bytes(stream, data: bytes) -> None:
    if data:
        stream.write(data)
        stream.flush()


def capture_command(argv, stdout, stderr, *, max_bytes=MAX_OUTPUT_BYTES,
                    buffer_seconds=MAX_BUFFER_SECONDS):
    """Bound memory and silence duration; always drain stdout and stderr together."""
    # Avoid a second Headroom pass in the native RTK launcher. Every other child
    # environment value remains exactly as supplied by the original command.
    child_env = dict(os.environ, HEADROOM_COMMAND_ACTIVE='1')
    process = subprocess.Popen(argv, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               shell=False, bufsize=0, env=child_env)
    lock = threading.Lock()
    buffered = bytearray()
    counters = {'stdout': 0, 'stderr': 0}
    state = {'passthrough': False, 'reason': None}

    def release(reason):
        if not state['passthrough']:
            state.update(passthrough=True, reason=reason)
            write_bytes(stdout, bytes(buffered))
            buffered.clear()

    def reader(pipe, name):
        try:
            while True:
                chunk = pipe.read(16384)
                if not chunk:
                    break
                with lock:
                    counters[name] += len(chunk)
                    if name == 'stderr':
                        write_bytes(stderr, chunk)
                    if sum(counters.values()) > max_bytes:
                        release('size_limit')
                    if name == 'stdout':
                        if state['passthrough']:
                            write_bytes(stdout, chunk)
                        else:
                            buffered.extend(chunk)
        finally:
            pipe.close()

    readers = [threading.Thread(target=reader, args=(process.stdout, 'stdout'), daemon=True),
               threading.Thread(target=reader, args=(process.stderr, 'stderr'), daemon=True)]
    for reader_thread in readers:
        reader_thread.start()
    deadline = time.monotonic() + buffer_seconds
    while process.poll() is None:
        if time.monotonic() >= deadline:
            with lock:
                release('streaming_timeout')
        try:
            process.wait(timeout=0.05)
        except subprocess.TimeoutExpired:
            pass
    # Normal command pipes drain immediately. Do not hang if a detached descendant
    # inherits them: release what was read and let process teardown close handles.
    for reader_thread in readers:
        reader_thread.join(timeout=1)
    with lock:
        if any(reader_thread.is_alive() for reader_thread in readers):
            release('inherited_pipe')
        return process.returncode, bytes(buffered), dict(counters), state['reason']


def filter_in_worker(original: bytes, state_dir: Path) -> CompressionResult:
    """An SDK/cache failure or deadline must never prevent original output delivery."""
    env = dict(os.environ, HEADROOM_WORKSPACE_DIR=str(state_dir))
    try:
        worker = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--filter-worker'],
                                input=original, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                env=env, timeout=COMPRESSION_TIMEOUT_SECONDS, check=True)
        result = json.loads(worker.stdout)
        result['output'] = base64.b64decode(result['output'], validate=True)
        parsed = CompressionResult(**result)
        if parsed.status != 'compressed':
            parsed.output = original
        elif (not parsed.content_hash or parsed.input_tokens is None or parsed.output_tokens is None
              or parsed.input_tokens <= parsed.output_tokens or len(parsed.output) >= len(original)):
            raise ValueError('Invalid compression worker result')
        return parsed
    except subprocess.TimeoutExpired:
        return CompressionResult(original, 'compression_timeout')
    except Exception:
        return CompressionResult(original, 'compression_unavailable')


def record_in_worker(result: CompressionResult, state_dir: Path, executable: str,
                     return_code: int, stdout_bytes: int, stderr_bytes: int) -> None:
    """Bound bookkeeping separately, after output delivery; failure can only undercount."""
    payload = asdict(result)
    payload.pop('output')
    request = dict(result=payload, executable=executable, return_code=return_code,
                   stdout_bytes=stdout_bytes, stderr_bytes=stderr_bytes)
    try:
        subprocess.run([sys.executable, str(Path(__file__).resolve()), '--record-result'],
                       input=json.dumps(request).encode(), stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL,
                       env=dict(os.environ, HEADROOM_WORKSPACE_DIR=str(state_dir)),
                       timeout=RECORD_TIMEOUT_SECONDS, check=True)
    except Exception:
        pass


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    automatic = bool(args and args[0] == '--cts-automatic')
    if automatic:
        args.pop(0)
    state_dir = Path(os.environ.get('HEADROOM_WORKSPACE_DIR', ROOT / 'headroom/desktop-state'))
    if args in (['--filter-worker'], ['--filter-packet']):
        if args == ['--filter-packet']:
            # .NET Framework may prepend a UTF-8 BOM to redirected stdin. The
            # protocol BOM is separate from original command bytes inside base64.
            packet_bytes = sys.stdin.buffer.read(2 * MAX_OUTPUT_BYTES + 1)
            if len(packet_bytes) > 2 * MAX_OUTPUT_BYTES:
                raise ValueError('Compression packet exceeds the bounded input size')
            packet = json.loads(packet_bytes.decode('utf-8-sig'))
            original = base64.b64decode(packet['input'], validate=True)
            if len(original) > MAX_OUTPUT_BYTES:
                raise ValueError('Compression packet output exceeds 2 MiB')
        else:
            original = sys.stdin.buffer.read(MAX_OUTPUT_BYTES + 1)
        configure_offline_environment(state_dir)
        result = CommandCompressor(state_dir).process(original, return_code=0)
        encoded = asdict(result)
        encoded['output'] = base64.b64encode(result.output).decode('ascii')
        sys.stdout.write(json.dumps(encoded))
        return 0
    if args == ['--record-result']:
        request = json.loads(sys.stdin.buffer.read(4 * MAX_OUTPUT_BYTES).decode('utf-8-sig'))
        payload = dict(request.pop('result'))
        # Output bytes are unnecessary for accounting, and may be omitted by a
        # native launcher after it has independently selected the emitted bytes.
        payload['output'] = b''
        result = CompressionResult(**payload)
        CommandCompressor(state_dir).record(result, **request)
        sys.stdout.write('{"recorded":true}')
        return 0
    explicit_exact = bool(args and args[0] == '--exact')
    explicit_activity = not automatic and os.environ.get('CTS_LAYA_INTERNAL') != '1'

    def observed(outcome, error_code=None):
        if explicit_activity:
            try:
                from bundle_activity import record
                record(ROOT, 'headroom_local', outcome, task_id=os.environ.get('CODEX_THREAD_ID'),
                       kind='diagnostic' if os.environ.get('CTS_ACTIVITY_KIND') == 'diagnostic' else 'operation',
                       error_code=error_code)
            except Exception:
                pass  # Reporting must never change command output or exit status.

    def finished(code):
        observed('completed' if code == 0 else 'failed', None if code == 0 else 'command_failed')
        return code

    if explicit_exact:
        args.pop(0)
    # The preference may be set by an earlier statement in the same shell
    # command, after its PreToolUse hook ran. Read it at execution time.
    exact = explicit_exact or os.environ.get('HEADROOM_EXACT') == '1'
    disabled = not load_preferences(ROOT)['headroom_local']
    if not args or args.pop(0) != '--' or not args:
        sys.stderr.write('Usage: headroom-run [--exact] -- <absolute executable> [arguments...]\n')
        observed('blocked', 'invalid_input')
        return 64
    executable = Path(args[0])
    if not executable.is_absolute() or (os.name == 'nt' and executable.suffix.lower() != '.exe'):
        sys.stderr.write('headroom-run requires an absolute executable path; shell scripts are not supported.\n')
        observed('blocked', 'invalid_input')
        return 64
    if not automatic and not disabled and not exact and os.environ.get('CTS_LAYA_INTERNAL') != '1':
        from laya_dispatch import authorize_explicit
        try:
            authorize_explicit(ROOT, 'headroom_local', 'command_output', task_id=os.environ.get('CODEX_THREAD_ID'))
        except (ValueError, RuntimeError, OSError) as exc:
            sys.stderr.write('headroom-run: Laya must authorize explicit bundle work. ' + str(exc) + '\n')
            observed('blocked', getattr(exc, 'code', 'router_unavailable'))
            return 126
    # In terminal/interactive mode preserve inherited console streams. General
    # Codex command hooks also exclude known interactive/watch/stdin commands.
    # Windows Codex gives ordinary piped commands a console stdin handle too;
    # stdin.isatty() alone therefore does not identify an interactive invocation.
    if disabled or exact or sys.stdout.isatty() or sys.stderr.isatty():
        try:
            completed = subprocess.run(args, shell=False,
                                       env=dict(os.environ, HEADROOM_COMMAND_ACTIVE='1'))
        except OSError as exc:
            sys.stderr.write(f'headroom-run: executable could not start: {exc}\n')
            observed('failed', 'runtime_missing')
            return 127
        result = CompressionResult(b'', 'disabled' if disabled else
                                   'exact_requested' if exact else 'interactive_passthrough')
        record_in_worker(result, state_dir, str(executable), completed.returncode, 0, 0)
        return finished(completed.returncode)
    try:
        return_code, captured, counters, reason = capture_command(args, sys.stdout.buffer, sys.stderr.buffer)
    except OSError as exc:
        sys.stderr.write(f'headroom-run: executable could not start: {exc}\n')
        observed('failed', 'runtime_missing')
        return 127
    if reason:
        result = CompressionResult(b'', reason)
    elif return_code != 0:
        result = CompressionResult(captured, 'command_failed')
    elif len(captured) < MIN_OUTPUT_BYTES:
        result = CompressionResult(captured, 'small_output')
    else:
        result = filter_in_worker(captured, state_dir)
    write_bytes(sys.stdout.buffer, result.output)
    record_in_worker(result, state_dir, str(executable), return_code,
                     counters['stdout'], counters['stderr'])
    return finished(return_code)


if __name__ == '__main__':
    sys.exit(main())
