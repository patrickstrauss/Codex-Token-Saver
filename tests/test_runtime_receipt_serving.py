"""A competing startup must not replace proof for the process serving requests."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import proxy_runtime


class RuntimeReceiptServingTests(unittest.TestCase):
    def test_failed_bind_never_publishes_a_serving_receipt(self):
        from headroom.proxy import server
        app = SimpleNamespace(add_middleware=lambda middleware: None)

        def failed_server(config, **kwargs):
            server.create_app(config)
            raise OSError('address already in use')

        with patch.object(proxy_runtime, '_configure_sdk', return_value=object()), \
             patch.object(proxy_runtime, '_write_exact_retrieval_runtime_receipt') as publish, \
             patch.object(server, 'create_app', return_value=app) as factory, \
             patch.object(server, 'run_server', side_effect=failed_server):
            with self.assertRaises(OSError):
                proxy_runtime.main(['--serve'])
            publish.assert_not_called()
            self.assertIs(server.create_app, factory, 'Temporary SDK factory must be restored')

    def test_lifespan_does_not_publish_and_real_requests_publish_once(self):
        calls = []
        async def app(scope, receive, send):
            calls.append(scope)
        wrapper = proxy_runtime.ExactRetrievalReceipt(app)
        scopes = [{'type': 'lifespan'}, {'type': 'http', 'path': '/health'},
                  {'type': 'websocket', 'path': '/responses'}, {'type': 'http', 'path': '/stats'}]
        with patch.object(proxy_runtime, '_write_exact_retrieval_runtime_receipt') as publish:
            asyncio.run(wrapper(scopes[0], None, None))
            publish.assert_not_called()
            for scope in scopes[1:]:
                asyncio.run(wrapper(scope, None, None))
            publish.assert_called_once_with()
        self.assertEqual(calls, scopes)

    def test_websocket_first_also_publishes(self):
        async def app(scope, receive, send):
            return None
        with patch.object(proxy_runtime, '_write_exact_retrieval_runtime_receipt') as publish:
            asyncio.run(proxy_runtime.ExactRetrievalReceipt(app)({'type': 'websocket'}, None, None))
            publish.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
