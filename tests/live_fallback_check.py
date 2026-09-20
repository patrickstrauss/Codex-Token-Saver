"""Manual integration check: unrelated Headroom-port service is left untouched."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
from urllib.request import urlopen

root = Path(__file__).resolve().parents[1]
config = Path.home() / '.codex/config.toml'
before = hashlib.sha256(config.read_bytes()).hexdigest()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok","service":"owned-test-fixture"}')
    def log_message(self, *args):
        pass

server = ThreadingHTTPServer(('127.0.0.1', 8787), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    result = subprocess.run([sys.executable, str(root / 'launch_codex.py'),
        '--experimental-headroom', '--', '--version'], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert 'Launching Codex directly' in result.stderr
    with urlopen('http://127.0.0.1:8787/health', timeout=2) as response:
        assert json.load(response)['service'] == 'owned-test-fixture'
    assert hashlib.sha256(config.read_bytes()).hexdigest() == before
    evidence = {'passed': True, 'unrelated_listener_preserved': True,
        'config_unchanged': True, 'launcher_exit': result.returncode,
        'version': result.stdout.strip(), 'notice': result.stderr.strip()}
    (root / 'logs/live-fallback-result.json').write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence))
finally:
    server.shutdown()
    server.server_close()
