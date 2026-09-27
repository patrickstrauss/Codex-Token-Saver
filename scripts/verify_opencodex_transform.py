"""Offline consumer/adapter witness. No installed routing or provider credentials are used."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ocx-source', type=Path, required=True)
    parser.add_argument('--bun', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, bun, output = (p.resolve() for p in (args.ocx_source, args.bun, args.output))
    fixture = source / 'tests/responses/token-saver-wire.test.ts'
    if not fixture.is_file() or not bun.is_file():
        parser.error('Provide the prepared OpenCodex source checkout and Bun executable.')
    import uvicorn
    from request_transform import OriginalStore, TransformService
    from request_transform_service import create_transform_app
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cts-ocx-witness-') as temporary:
        root = Path(temporary)
        service = TransformService(lambda text: 'worker diagnostic summary', OriginalStore(root / 'originals.db'),
                                   root=root, token_counter=len)
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_transform_app(service, token='a' * 64),
                                host='127.0.0.1', port=port, log_level='error', access_log=False))
        thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        thread.start()
        started = time.monotonic()
        result = None
        failure = None
        try:
            while not server.started and thread.is_alive() and time.monotonic() - started < 5:
                time.sleep(.05)
            if not server.started:
                raise RuntimeError('Isolated transform service did not start.')
            environment = dict(os.environ, CTS_TRANSFORM_TEST_URL=f'http://127.0.0.1:{port}')
            result = subprocess.run([str(bun), 'test', str(fixture),
                                    str(source / 'tests/responses/token-saver-pipeline.test.ts')],
                                    cwd=source, env=environment,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            failure = type(exc).__name__
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            listener.close()
            service.close()
        passed = result is not None and result.returncode == 0 and not thread.is_alive()
        report = {
            'kind': 'offline-consumer-adapter-witness',
            'passed': passed,
            'coverage': ['real-transform-http', 'unicode-exact-retrieval', 'responses-serialization',
                         'chat-serialization', 'original-unchanged', 'one-transform-for-rebuilds',
                         'two-expected-local-provider-sends', 'three-expected-mocked-core-sends',
                         'http-and-websocket-prepared-core', 'native-forward-core'],
            'not_qualified': ['full-server-http-websocket', 'native-steering-injection', 'migration',
                              'windows-reboot', 'real-openai-azure-lm-studio'],
            'transform_counts': service.counts,
            'elapsed_seconds': round(time.monotonic() - started, 3),
            'cleanup_ok': not thread.is_alive(),
            'failure': failure,
            'source_hashes': {str(path.relative_to(source)).replace('\\', '/'):
                hashlib.sha256(path.read_bytes()).hexdigest() for path in [
                    fixture, source / 'src/integrations/token-saver.ts',
                    source / 'tests/responses/token-saver-pipeline.test.ts',
                    source / 'src/server/responses/request-transport.ts']},
        }
        output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        output.with_suffix('.log').write_bytes(result.stdout if result else b'Service did not start.')
        print(json.dumps({'passed': passed, 'report': str(output), 'cleanup_ok': report['cleanup_ok']}))
        return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
