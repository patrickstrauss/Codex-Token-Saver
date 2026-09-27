"""Contract tests against an isolated HTTP server; no production originals."""

from contextlib import contextmanager
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch


if importlib.util.find_spec("proxy_retrieval") is not None:
    import proxy_retrieval
else:
    proxy_retrieval = None

HASH = "012345abcdef"
HEALTH = {"service": "headroom-proxy", "status": "healthy", "ready": True}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.hits.append(self.path)
        self.server.last_authorization = self.headers.get('Authorization')
        status, body, headers = self.server.routes.get(self.path, (404, b"missing", {}))
        self.send_response(status)
        self.send_header("Content-Type", headers.get("Content-Type", "application/json"))
        for name, value in headers.items():
            if name.lower() != "content-type":
                self.send_header(name, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def log_message(self, *_args):
        pass


class ProxyRetrievalTests(unittest.TestCase):
    def test_transform_retrieval_uses_private_token_only_after_identity_check(self):
        with self.service() as original, tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'proxy').mkdir()
            (root / 'proxy/transform-token').write_text('a' * 64)
            self.server.routes['/health'] = (200, json.dumps({**HEALTH, 'mode': 'transform-only'}).encode(), {})
            self.assertEqual(proxy_retrieval.read_proxy_original(HASH, root=root), original)
            self.assertEqual(self.server.last_authorization, 'Bearer ' + 'a' * 64)

    def test_proxy_retrieval_feature_exists(self):
        self.assertIsNotNone(proxy_retrieval, "The proxy original-content bridge is missing.")

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(timeout=2)

    @contextmanager
    def service(self, original="line one\r\nภาษาไทย 😀\r\nlast\n"):
        if proxy_retrieval is None:
            self.skipTest("The feature-existence test reports the missing implementation.")
        self.server.hits = []
        self.server.routes = {
            "/health": (200, json.dumps(HEALTH).encode(), {}),
            f"/v1/retrieve/{HASH}": (
                200,
                json.dumps({"hash": HASH, "original_content": original}, ensure_ascii=False).encode(),
                {},
            ),
        }
        with patch.object(proxy_retrieval, "PROXY_ORIGIN", self.origin):
            yield original

    def test_exact_unicode_and_line_endings_are_returned_without_metrics(self):
        with self.service() as original:
            self.assertEqual(proxy_retrieval.read_proxy_original(HASH), original)
            self.assertEqual(self.server.hits, ["/health", f"/v1/retrieve/{HASH}"])

    def test_empty_original_is_valid(self):
        with self.service(""):
            self.assertEqual(proxy_retrieval.read_proxy_original(HASH), "")

    def test_default_origin_is_fixed_loopback(self):
        if proxy_retrieval is None:
            self.skipTest("Implementation pending.")
        self.assertEqual(proxy_retrieval.PROXY_ORIGIN, "http://127.0.0.1:8789")

    def test_invalid_ids_never_make_network_requests(self):
        with self.service():
            for value in (None, 12, "", "a" * 24, "A" * 12, "g" * 12, "../health", HASH + "/", HASH + "?x=1", "http://example.com"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    proxy_retrieval.read_proxy_original(value)
            self.assertEqual(self.server.hits, [])

    def test_does_not_use_environment_proxy(self):
        with self.service() as original, patch.dict(os.environ, {
            "http_proxy": "http://127.0.0.1:1", "HTTP_PROXY": "http://127.0.0.1:1",
            "https_proxy": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1",
            "all_proxy": "http://127.0.0.1:1", "ALL_PROXY": "http://127.0.0.1:1",
            "no_proxy": "", "NO_PROXY": "",
        }):
            self.assertEqual(proxy_retrieval.read_proxy_original(HASH), original)

    def test_foreign_listener_is_rejected_before_retrieval(self):
        with self.service():
            self.server.routes["/health"] = (200, b'{"service":"something-else","status":"healthy"}', {})
            with self.assertRaisesRegex(RuntimeError, "Headroom"):
                proxy_retrieval.read_proxy_original(HASH)
            self.assertEqual(self.server.hits, ["/health"])

    def test_warming_compressor_can_still_serve_existing_originals(self):
        with self.service() as original:
            self.server.routes["/health"] = (200, json.dumps({**HEALTH, "ready": False}).encode(), {})
            self.assertEqual(proxy_retrieval.read_proxy_original(HASH), original)

    def test_redirect_is_not_followed_from_health_or_retrieval(self):
        with self.service():
            for path in ("/health", f"/v1/retrieve/{HASH}"):
                with self.subTest(path=path):
                    before = self.server.routes[path]
                    self.server.hits = []
                    self.server.routes[path] = (302, b"", {"Location": self.origin + "/redirect-target"})
                    with self.assertRaises(RuntimeError):
                        proxy_retrieval.read_proxy_original(HASH)
                    self.assertNotIn("/redirect-target", self.server.hits)
                    self.server.routes[path] = before

    def test_expired_or_missing_original_is_a_lookup_error(self):
        with self.service():
            self.server.routes[f"/v1/retrieve/{HASH}"] = (404, b'{"detail":"expired"}', {})
            with self.assertRaisesRegex(LookupError, "expired"):
                proxy_retrieval.read_proxy_original(HASH)

    def test_missing_health_and_backend_failures_are_runtime_errors(self):
        with self.service():
            for path, status in (("/health", 404), (f"/v1/retrieve/{HASH}", 503)):
                with self.subTest(path=path):
                    before = self.server.routes[path]
                    self.server.routes[path] = (status, b"private diagnostic must not appear", {})
                    with self.assertRaises(RuntimeError) as raised:
                        proxy_retrieval.read_proxy_original(HASH)
                    self.assertNotIn("private diagnostic", str(raised.exception))
                    self.server.routes[path] = before

    def test_schema_hash_content_type_and_encoding_must_be_valid(self):
        invalid = [
            (b"not JSON", {}),
            (b"[]", {}),
            (b"null", {}),
            (json.dumps({"hash": "f" * 12, "original_content": "x"}).encode(), {}),
            (json.dumps({"hash": HASH, "original_content": 123}).encode(), {}),
            (json.dumps({"hash": HASH}).encode(), {}),
            (b'{"hash":"' + HASH.encode() + b'","original_content":"\xff"}', {}),
            (json.dumps({"hash": HASH, "original_content": "x"}).encode(), {"Content-Type": "text/html"}),
        ]
        with self.service():
            for body, headers in invalid:
                with self.subTest(body=body[:80], headers=headers):
                    self.server.routes[f"/v1/retrieve/{HASH}"] = (200, body, headers)
                    with self.assertRaises(RuntimeError):
                        proxy_retrieval.read_proxy_original(HASH)

    def test_oversized_response_is_rejected_even_without_content_length(self):
        with self.service():
            self.server.routes[f"/v1/retrieve/{HASH}"] = (200, b" " * (proxy_retrieval.MAX_RESPONSE_BYTES + 1), {})
            with self.assertRaisesRegex(RuntimeError, "large|limit"):
                proxy_retrieval.read_proxy_original(HASH)

    def test_transport_timeout_is_bounded_and_reported_cleanly(self):
        with self.service(), patch.object(proxy_retrieval, "build_opener") as factory:
            factory.return_value.open.side_effect = socket.timeout("private transport detail")
            with self.assertRaises(RuntimeError) as raised:
                proxy_retrieval.read_proxy_original(HASH)
            self.assertNotIn("private transport detail", str(raised.exception))
            self.assertEqual(factory.return_value.open.call_args.kwargs["timeout"], 3)


if __name__ == "__main__":
    unittest.main()
