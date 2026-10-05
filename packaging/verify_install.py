"""Smoke-test a fresh bundle without services, credentials, or user history."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def verify(root):
    sys.path.insert(0, str(root))
    # Headroom holds its SQLite cache until this check process exits on Windows.
    with tempfile.TemporaryDirectory(prefix='token-saver-install-check-', ignore_cleanup_errors=True) as temporary:
        state = Path(temporary)
        os.environ.update(
            CODEX_HOME=str(state / 'codex'), HEADROOM_WORKSPACE_DIR=str(state / 'headroom'),
            HEADROOM_OFFLINE='1', HEADROOM_TELEMETRY='off', HF_HUB_OFFLINE='1',
            TRANSFORMERS_OFFLINE='1', LITELLM_LOCAL_MODEL_COST_MAP='True',
            TIKTOKEN_CACHE_DIR=str(root / 'headroom/tokenizer-cache'),
            RTK_DB_PATH=str(state / 'rtk.db'), RTK_TELEMETRY_DISABLED='1',
        )
        from desktop_headroom import DesktopHeadroom, O200K_URL, O200K_SHA256
        # Validate packaged integration modules without probing or mutating live OpenCodex.
        from opencodex_control import fingerprint
        from request_transform_service import transform_enabled
        from proxy_runtime import build_proxy_command
        assert fingerprint(None) == hashlib.sha256(b'null').hexdigest()
        assert transform_enabled(state) is False
        assert '--serve-transform' in build_proxy_command(root / 'headroom/.venv', mode='opencodex')
        tokenizer = root / 'headroom/tokenizer-cache' / hashlib.sha1(O200K_URL.encode()).hexdigest()
        assert hashlib.sha256(tokenizer.read_bytes()).hexdigest() == O200K_SHA256
        backend = DesktopHeadroom(state / 'reads', bundle_root=root)
        fixture = state / 'example.json'
        original = json.dumps([{'id': number, 'status': 'ok', 'message': 'Synthetic installer check'} for number in range(150)], indent=2)
        fixture.write_bytes(original.encode('utf-8'))
        assert backend._count(original) > 0
        compressed = backend._compress(original)
        assert isinstance(compressed, str) and compressed
        exact = backend.read_file(str(fixture), compress=False, max_lines=10000)
        assert original in exact
        version = subprocess.check_output([str(root / 'bin/rtk.exe'), '--version'], text=True, timeout=30)
        assert 'rtk ' in version
        from cli_tools import runtime_paths, runtime_status, command
        _, cli_runtime, _ = runtime_paths(root)
        if cli_runtime.exists():
            assert runtime_status(root)['available'], 'CLI runtime is incomplete'
            for component in ('playwright_cli', 'ast_grep'):
                subprocess.run([*command(root, component), '--version'], check=True, timeout=30)
        if (root / 'laya/.venv/Scripts/python.exe').exists():
            from bundle_router import status as router_status
            assert router_status(root)['available'], 'Laya model inference has not been validated'
            from bundle_router_mcp import list_tools as router_tools
            import asyncio
            assert [tool.name for tool in asyncio.run(router_tools())] == ['bundle_query']
        dashboard = root / 'dashboard/.venv/Scripts/python.exe'
        subprocess.run([str(dashboard), '-c', 'import flask, dotenv, tomlkit; print("dashboard dependencies OK")'], check=True, timeout=30)
        for directory, imports in [('serena', 'import serena; import solidlsp'), ('local-compaction', 'import langmem; import langchain_openai')]:
            python = root / directory / '.venv/Scripts/python.exe'
            if python.is_file():
                subprocess.run([str(python), '-c', imports], check=True, timeout=120)
                if directory == 'serena':
                    from serena_mcp import probe_runtime
                    assert probe_runtime(root)['ok'], 'Serena navigation schemas are incompatible'
        llama = root / 'local-compaction/llama-b10809/llama-server.exe'
        if llama.is_file():
            subprocess.run([str(llama), '--version'], check=True, timeout=30, stdout=subprocess.DEVNULL)
    print(json.dumps({'validated': True, 'headroom': importlib.metadata.version('headroom-ai'), 'rtk': version.strip(), 'model_loaded': False}))


if __name__ == '__main__':
    verify(Path(sys.argv[1]).resolve())
