import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import tempfile
import unittest

from mcp.types import CallToolResult, TextContent
from bundle_preferences import set_preference
from serena_mcp import GatedSerenaBridge, LazySerenaSession


def result(text, error=False):
    return CallToolResult(isError=error, content=[TextContent(type='text', text=text)])


class SerenaLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.connections = []
        self.exits = asyncio.Queue()
        self.started = asyncio.Event()
        self.resume = asyncio.Event()
        self.slow = False
        self.fail = False

        @asynccontextmanager
        async def connect():
            owner = asyncio.current_task()
            test = self

            class Session:
                project = None

                async def call_tool(session, name, arguments):
                    if test.fail:
                        test.fail = False
                        raise ConnectionError('backend disconnected')
                    if name == 'activate_project':
                        if arguments['project'] == 'invalid':
                            return result('invalid project', error=True)
                        session.project = arguments['project']
                    elif test.slow:
                        test.started.set()
                        await test.resume.wait()
                    return result(session.project or 'no project')

            session = Session()
            self.connections.append(session)
            try:
                yield session
            finally:
                self.assertIs(asyncio.current_task(), owner, 'MCP contexts must exit in their owner task')
                self.exits.put_nowait(session)

        self.worker = LazySerenaSession(self.root, idle_seconds=0.03, connect=connect)
        self.addAsyncCleanup(self.worker.close)

    async def wait_idle(self):
        await asyncio.wait_for(self.exits.get(), 1)

    async def test_unused_and_disabled_connections_never_start_backend(self):
        await asyncio.sleep(0.04)
        self.assertEqual(self.connections, [])
        bridge = GatedSerenaBridge(self.root, self.worker, already_routed=True)
        self.assertTrue((await bridge.call_tool('find_symbol', {})).isError)
        set_preference(self.root, 'serena', True)
        self.assertTrue((await bridge.call_tool('activate_project', {'project': 'relative'})).isError)
        self.assertEqual(self.connections, [])

    async def test_idle_shutdown_restores_last_successful_project(self):
        await self.worker.call_tool('activate_project', {'project': 'checkout-A'})
        await self.wait_idle()
        response = await self.worker.call_tool('find_symbol', {})
        self.assertEqual(response.content[0].text, 'checkout-A')
        self.assertEqual(len(self.connections), 2)
        await self.worker.call_tool('activate_project', {'project': 'invalid'})
        await self.wait_idle()
        response = await self.worker.call_tool('find_symbol', {})
        self.assertEqual(response.content[0].text, 'checkout-A')

    async def test_inflight_lookup_survives_idle_deadline_and_client_cancellation(self):
        await self.worker.call_tool('activate_project', {'project': 'checkout-A'})
        self.slow = True
        call = asyncio.create_task(self.worker.call_tool('find_symbol', {}))
        await self.started.wait()
        call.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await call
        await asyncio.sleep(0.06)
        self.assertTrue(self.exits.empty())
        self.resume.set()
        await self.wait_idle()

    async def test_connections_do_not_share_active_project(self):
        other = LazySerenaSession(self.root, idle_seconds=0.03, connect=self.worker.connect)
        self.addAsyncCleanup(other.close)
        await self.worker.call_tool('activate_project', {'project': 'checkout-A'})
        await other.call_tool('activate_project', {'project': 'checkout-B'})
        self.assertEqual((await self.worker.call_tool('find_symbol', {})).content[0].text, 'checkout-A')
        self.assertEqual((await other.call_tool('find_symbol', {})).content[0].text, 'checkout-B')

    async def test_backend_failure_is_not_replayed_and_next_call_can_restart(self):
        await self.worker.call_tool('activate_project', {'project': 'checkout-A'})
        self.fail = True
        with self.assertRaises(ConnectionError):
            await self.worker.call_tool('find_symbol', {})
        await self.wait_idle()
        self.assertEqual(len(self.connections), 1)
        self.assertEqual((await self.worker.call_tool('find_symbol', {})).content[0].text, 'checkout-A')

    async def test_close_unloads_backend_and_rejects_further_work(self):
        await self.worker.call_tool('activate_project', {'project': 'checkout-A'})
        await self.worker.close()
        self.assertFalse(self.exits.empty())
        with self.assertRaises(RuntimeError):
            await self.worker.call_tool('find_symbol', {})

    async def test_startup_failure_finishes_request_and_allows_retry(self):
        original = self.worker.connect
        failed = False

        @asynccontextmanager
        async def connect():
            nonlocal failed
            if not failed:
                failed = True
                raise OSError('runtime failed to start')
            async with original() as session:
                yield session

        self.worker.connect = connect
        with self.assertRaises(RuntimeError):
            await asyncio.wait_for(self.worker.call_tool('activate_project', {'project': 'checkout-A'}), 1)
        response = await self.worker.call_tool('activate_project', {'project': 'checkout-A'})
        self.assertEqual(response.content[0].text, 'checkout-A')

    async def test_new_lookup_waits_for_idle_cleanup_before_restarting(self):
        original = self.worker.connect
        closing = asyncio.Event()
        finish = asyncio.Event()

        @asynccontextmanager
        async def connect():
            async with original() as session:
                try:
                    yield session
                finally:
                    closing.set()
                    await finish.wait()

        self.worker.connect = connect
        await self.worker.call_tool('activate_project', {'project': 'checkout-A'})
        await asyncio.wait_for(closing.wait(), 1)
        lookup = asyncio.create_task(self.worker.call_tool('find_symbol', {}))
        await asyncio.sleep(0.04)
        self.assertFalse(lookup.done())
        self.assertEqual(len(self.connections), 1)
        finish.set()
        self.assertEqual((await lookup).content[0].text, 'checkout-A')
        self.assertEqual(len(self.connections), 2)


if __name__ == '__main__':
    unittest.main()
