"""On-demand, per-connection Serena backend with safe idle cleanup."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import sys


class LazySerenaSession:
    def __init__(self, root, *, idle_seconds=120, connect=None):
        if idle_seconds <= 0:
            raise ValueError('Serena idle timeout must be positive.')
        self.root = Path(root).resolve()
        self.idle_seconds = idle_seconds
        self.connect = connect or self._connect
        self._lock = asyncio.Lock()
        self._owner = None
        self._queue = None
        self._project = None
        self._closed = False

    @asynccontextmanager
    async def _connect(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from serena_mcp import launch_spec, validate_navigation_tools
        command, environment = launch_spec(self.root)
        environment.pop('CTS_LAYA_INTERNAL', None)
        params = StdioServerParameters(command=command[0], args=command[1:], env=environment, cwd=str(self.root))
        async with stdio_client(params, errlog=sys.stderr) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                validate_navigation_tools(self.root, (await session.list_tools()).tools)
                yield session

    async def call_tool(self, name, arguments):
        async with self._lock:
            if self._closed:
                raise RuntimeError('Serena connection is closed.')
            if self._queue is None:
                if self._owner is not None:
                    await asyncio.shield(self._owner)
                self._queue = asyncio.Queue()
                self._owner = asyncio.create_task(self._serve(self._queue))
            future = asyncio.get_running_loop().create_future()
            self._queue.put_nowait((name, dict(arguments), future))
            # Caller cancellation cannot interrupt an already dispatched backend lookup.
            return await future

    async def _serve(self, queue):
        future = None
        current_project = None
        try:
            # AnyIO's MCP contexts must enter and exit in this single owner task.
            async with self.connect() as session:
                try:
                    while True:
                        try:
                            request = await asyncio.wait_for(queue.get(), timeout=self.idle_seconds)
                        except TimeoutError:
                            # wait_for can finish cancelling its empty get after
                            # a caller queues work at the idle deadline. Consume
                            # that request instead of draining it as unavailable.
                            if queue.empty():
                                return
                            continue
                        if request is None:
                            return
                        name, arguments, future = request
                        if future.cancelled():
                            continue
                        if name != 'activate_project' and self._project != current_project:
                            restored = await session.call_tool('activate_project', {'project': self._project})
                            if restored.isError:
                                raise RuntimeError('Serena could not restore the active checkout; activate it again.')
                            current_project = self._project
                        response = await session.call_tool(name, arguments)
                        if name == 'activate_project' and not response.isError:
                            self._project = current_project = arguments['project']
                        if not future.done():
                            future.set_result(response)
                        future = None
                finally:
                    # Calls arriving during cleanup wait for this owner before restarting.
                    self._queue = None
        except Exception as exc:
            if future is not None and not future.done():
                future.set_exception(exc)
        finally:
            self._queue = None
            while not queue.empty():
                request = queue.get_nowait()
                if request is not None and not request[2].done():
                    request[2].set_exception(RuntimeError('Serena backend unavailable; retry navigation.'))

    async def close(self):
        async with self._lock:
            self._closed = True
            if self._queue is not None:
                self._queue.put_nowait(None)
            if self._owner is not None:
                await asyncio.shield(self._owner)
