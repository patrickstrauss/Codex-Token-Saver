"""Exercise competing backend launches on an isolated port and temporary state."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from local_summary_engine import _windows_job
from proxy_runtime import build_proxy_command, build_proxy_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path)
    args = parser.parse_args()
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
    opener = build_opener(ProxyHandler({}))
    with tempfile.TemporaryDirectory(prefix='headroom-serving-proof-') as temporary:
        state = Path(temporary)
        assert state.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
        command = build_proxy_command(args.runtime, port=port)
        env = build_proxy_environment(state)
        processes, closers = [], []
        with (state / 'test.log').open('wb') as log:
            def launch():
                process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=log,
                                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                processes.append(process)
                closers.append(_windows_job(process))
                return process
            try:
                owner = launch()
                deadline = time.monotonic() + 40
                while True:
                    if owner.poll() is not None:
                        raise RuntimeError('Isolated backend exited before readiness')
                    try:
                        with opener.open(f'http://127.0.0.1:{port}/health', timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        pass
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Isolated backend did not become ready')
                    time.sleep(0.1)
                receipt = state / 'exact-retrieval-runtime.json'
                before = receipt.read_bytes()
                proof = json.loads(before)
                assert proof['protected'] is True
                assert all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == value
                           for name, value in proof['source_hashes'].items())
                duplicate = launch()
                assert duplicate.wait(timeout=30) != 0, 'Duplicate unexpectedly acquired occupied port'
                assert receipt.read_bytes() == before, 'Failed duplicate replaced the serving receipt'
                assert owner.poll() is None
                with opener.open(f'http://127.0.0.1:{port}/health', timeout=2) as response:
                    assert response.status == 200
            finally:
                for close in reversed(closers):
                    close()
                for process in processes:
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=10)
        # Job termination is asynchronous: the Windows venv redirector can
        # exit just before its child releases the inherited log handle.
        deadline = time.monotonic() + 5
        while True:
            try:
                (state / 'test.log').unlink()
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
    print(json.dumps({'ok': True, 'ready_backend_published_proof': True,
                      'failed_duplicate_preserved_proof': True,
                      'serving_backend_unchanged': True, 'isolated_state': True,
                      'temporary_state_removed': True}))


if __name__ == '__main__':
    main()
