"""One loopback, authenticated local classifier; no tool execution in this process."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import time

RECIPES = {
    'file_read': 'Read the contents of a local file or log.',
    'symbols': 'Find code symbols, definitions or references.',
    'ast_search': 'Match a structural syntax pattern in source code.',
    'git_report': 'Inspect git changes, status or commit history.',
    'browser_snapshot': 'Read the current page in an existing browser session.',
    # Keep the calibrated choice menu stable. This negative class has no tool,
    # executable recipe or component; it is folded into clarification below.
    'unavailable': 'Read or explicitly request a local task summary.',
    'clarify': 'No available tool fits, or the request is ambiguous.',
}


class Classifier:
    def __init__(self, root):
        os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                          TOKENIZERS_PARALLELISM='false', CUDA_VISIBLE_DEVICES='')
        import torch
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        from laya import Agent
        manifest = json.loads((root / 'packaging/laya-model.json').read_bytes())
        # Upstream normalizes tokenizer_config.json in place. Preserve the
        # downloaded artifacts and rebuild a private, verified working copy.
        working = root / 'laya/model-runtime'
        for item in manifest['files']:
            target = working / item['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            if item['path'] != 'model.safetensors' or not target.exists():
                shutil.copy2(root / 'laya/model' / item['path'], target)
        self.agent = Agent(str(working), device='cpu', compile=False,
                           expected_sha256={item['path']: item['sha256'] for item in manifest['files']})

    def predict(self, intent):
        if not isinstance(intent, str) or not 1 <= len(intent) <= 1200:
            raise ValueError('Provide a short routing intent (1-1200 characters).')
        # Keep label order and alternatives stable: changing the menu altered
        # predictions materially in qualification. The executor applies current
        # component availability and required-argument constraints afterwards.
        questions = {'route': {'type': 'choice', 'instructions': 'Choose the tool that best performs this requested task.',
                              'criteria': RECIPES},
                     'delivery': {'type': 'choice', 'instructions': 'Should the result preserve exact content or be condensed?',
                                  'criteria': {'exact': 'Exact source, quotation, precise edit or complete evidence.',
                                               'compact': 'Concise overview or exploratory inspection.'}}}
        started = time.monotonic()
        result = self.agent.system_one(intent, questions)
        answer = result['answers']['route']
        delivery = result['answers']['delivery']['choice']
        route = 'clarify' if answer['choice'] == 'unavailable' else answer['choice']
        return {'route': route, 'confidence': answer['probabilities'][answer['choice']],
                'delivery': delivery, 'truncated': result.get('usage', {}).get('truncated', False),
                'elapsed_ms': round((time.monotonic() - started) * 1000, 1)}


def serve(root):
    from bundle_preferences import load_preferences
    token = (root / 'laya/service-key.txt').read_text().strip()
    classifier = None
    last_use = time.monotonic()

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass

        def reply(self, value, code=200):
            data = json.dumps(value).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            return (self.headers.get('Host') == '127.0.0.1:8791' and not self.headers.get('Origin')
                    and secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token))

        def do_GET(self):
            if not self.authorized():
                return self.reply({'error': 'Unauthorized'}, 403)
            if self.path != '/health':
                return self.reply({'error': 'Unknown path'}, 404)
            self.reply({'service': 'cts-laya-router', 'ready': True, 'model_loaded': classifier is not None})

        def do_POST(self):
            nonlocal classifier, last_use
            if not self.authorized():
                return self.reply({'error': 'Unauthorized'}, 403)
            if self.path != '/route' or not load_preferences(root)['laya_router']:
                return self.reply({'error': 'Router disabled or path unavailable'}, 409)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 16384:
                    raise ValueError('Bounded request required.')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict) or set(body) != {'intent'}:
                    raise ValueError('Invalid request.')
                last_use = time.monotonic()
                if classifier is None:
                    classifier = Classifier(root)
                result = classifier.predict(**body)
                last_use = time.monotonic()
                self.reply(result)
            except Exception:
                self.reply({'error': 'Local routing unavailable; use a direct tool or narrow the intent.'}, 503)

    server = HTTPServer(('127.0.0.1', 8791), Handler)
    server.timeout = 1
    while load_preferences(root)['laya_router'] and time.monotonic() - last_use < 300:
        server.handle_request()
    server.server_close()  # Disabled/idle processes exit and release model RAM.


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--probe', action='store_true')
    args = parser.parse_args()
    if args.probe:
        classifier = Classifier(args.root)
        print(json.dumps(classifier.predict('Find function definitions and their symbols in the code.')))
    else:
        serve(args.root.resolve())
