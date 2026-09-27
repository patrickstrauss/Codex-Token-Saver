"""Isolated Headroom request backend for the desktop's loopback supervisor.

The command/environment builders import only stdlib. SDK and model imports run
in the backend child, so a slow or broken native dependency cannot block the
front door. Policy follows Headroom Desktop's pinned 0.37.0 coding/token setup,
with output/model/effort steering disabled to retain the user's choices.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
MODEL_CACHE = ROOT / 'models' / 'huggingface'
UPSTREAM_REFERENCE = 'gglucass/headroom-desktop@7379fbf5d371d382eee9e58e9c1707cbfba6aded'

# Explicit values win over profile defaults and stale CLI proxy settings.
_POLICY = {
    'HEADROOM_SDK': 'codex-token-saver-desktop-proxy',
    'HEADROOM_SAVINGS_PROFILE': 'coding',
    'HEADROOM_MODE': 'token',
    'HEADROOM_DEDUPE': '1',
    'HEADROOM_BACKGROUND_COMPRESSION': '1',
    'HEADROOM_PROXY_AUTH_MODE_POLICY_ENFORCEMENT': 'enabled',
    'HEADROOM_ROLLOUT_CHANNEL': 'beta',
    'HEADROOM_READ_MATURATION': '1',
    'HEADROOM_READ_MATURATION_QUIESCE_TURNS': '5',
    'HEADROOM_READ_MATURATION_MAX_HOLD_TURNS': '25',
    'HEADROOM_READ_MATURATION_MIN_SIZE_BYTES': '2048',
    'HEADROOM_COLD_RECOMPACT': '1',
    'HEADROOM_CACHE_TTL_LEARN': '1',
    'HEADROOM_CODE_AWARE_ENABLED': '1',
    'HEADROOM_LOSSLESS_THEN_LOSSY': '1',
    'HEADROOM_PROTECT_READS': '1',
    'HEADROOM_PROTECT_ANALYSIS_CONTEXT': '1',
    'HEADROOM_COMPRESS_USER_MESSAGES': '0',
    'HEADROOM_COMPRESS_SYSTEM_MESSAGES': '0',
    'HEADROOM_MIN_TOKENS': '10',
    'HEADROOM_MIN_CHARS_FOR_BLOCK': '25',
    'HEADROOM_SMART_CRUSHER_COMPACTION': '1',
    'HEADROOM_DISABLE_KOMPRESS': '0',
    'HEADROOM_DISABLE_KOMPRESS_OPENAI': '0',
    'HEADROOM_KOMPRESS_BACKEND': 'onnx_cpu',
    'HEADROOM_KOMPRESS_ONNX_FILENAME': 'onnx/kompress-int8-wo.onnx',
    'HEADROOM_KOMPRESS_ONNX_INTRA_THREADS': '2',
    'HEADROOM_KOMPRESS_ONNX_INTER_THREADS': '1',
    'HEADROOM_KOMPRESS_MAX_CONCURRENT': '1',
    'HEADROOM_KOMPRESS_TIME_BUDGET_SECONDS': '3',
    'HEADROOM_KOMPRESS_ACQUIRE_TIMEOUT_SECONDS': '0.25',
    'HEADROOM_COMPRESSION_TIMEOUT_SECONDS': '5',
    'HEADROOM_COLD_START_FAST_PASS_TIMEOUT_SECONDS': '1',
    'HEADROOM_EAGER_PRELOAD_TIMEOUT_SECONDS': '10',
    'HEADROOM_OUTPUT_SHAPER': '0',
    'HEADROOM_EFFORT_ROUTER': '0',
    'HEADROOM_MODEL_ROUTER_ENABLED': '0',
    'HEADROOM_VERBOSITY_AUTOTUNE': '0',
    'HEADROOM_VERBOSITY_LEVEL': '0',
    'HEADROOM_OUTPUT_HOLDOUT': '0',
    'HEADROOM_DISABLE_FEATURES': 'proxy_output_shaper,tool_result_interceptors',
    'HEADROOM_CC_SWITCH_RECONCILE': '0',
    'HEADROOM_TELEMETRY': 'off',
    'HEADROOM_BEACON': 'off',
    'HEADROOM_UPDATE_CHECK': 'off',
    'HEADROOM_LOG_MESSAGES': '0',
    'HEADROOM_DEBUG_DUMP': '0',
    'HEADROOM_CODEX_WIRE_DEBUG': '0',
    'HEADROOM_LOG_LEVEL': 'warning',
    'HEADROOM_HTTP2': 'false',
    'HEADROOM_MAX_KEEPALIVE': '0',
    'HF_HUB_OFFLINE': '1',
    'TRANSFORMERS_OFFLINE': '1',
    'HF_HUB_DISABLE_TELEMETRY': '1',
    'HF_HUB_DISABLE_XET': '1',
    'DO_NOT_TRACK': '1',
    'PYTHONNOUSERSITE': '1',
    'PYTHONUNBUFFERED': '1',
    'TOKENIZERS_PARALLELISM': 'false',
}


def build_proxy_environment(state_dir, inherited=None):
    """Return a child-only environment; never mutate settings or host env.

    Inherited provider URLs/authentication are retained exactly. All Headroom
    overrides are discarded before applying managed policy, including alternate
    state paths, debug dumps, serialized config, and model-routing rules.
    """
    state = Path(state_dir)
    if not state.is_absolute():
        raise ValueError('Proxy state directory must be absolute')
    state = state.resolve()
    source = os.environ if inherited is None else inherited
    replaced = set(_POLICY) | {
        'PYTHONHOME', 'PYTHONPATH', 'HF_HOME', 'HF_HUB_CACHE', 'TIKTOKEN_CACHE_DIR',
        'HUGGINGFACE_HUB_CACHE', 'TRANSFORMERS_CACHE',
        'PYTORCH_TRANSFORMERS_CACHE', 'PYTORCH_PRETRAINED_BERT_CACHE',
    }
    env = {key: value for key, value in source.items()
           if not key.upper().startswith('HEADROOM_')
           and key.upper() not in replaced}
    env.update(_POLICY)
    env.update({
        'HEADROOM_WORKSPACE_DIR': str(state),
        'HEADROOM_CONFIG_DIR': str(state / 'config'),
        'HEADROOM_CACHE_TTL_LEARNED_PATH': str(state / 'cache_ttl.json'),
        'HF_HOME': str(MODEL_CACHE),
        'HF_HUB_CACHE': str(MODEL_CACHE / 'hub'),
        'TIKTOKEN_CACHE_DIR': str(ROOT / 'models' / 'tiktoken'),
    })
    return env


def _endpoint(host, port):
    if host != '127.0.0.1':
        raise ValueError('Managed Headroom binds only to 127.0.0.1')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Proxy port is invalid')


def _python(runtime):
    value = runtime.get('runtime') if isinstance(runtime, Mapping) else runtime
    path = Path(value)
    if not path.is_absolute():
        raise ValueError('Runtime directory must be absolute')
    python = path.resolve() / 'Scripts' / 'python.exe'
    if not python.is_file():
        raise ValueError('Managed runtime interpreter is missing')
    return str(python)


def build_proxy_command(runtime, host='127.0.0.1', port=8789):
    """Return argv for a dedicated interpreter; caller uses shell=False."""
    _endpoint(host, port)
    return [_python(runtime), str(Path(__file__).resolve()), '--serve',
            '--host', host, '--port', str(port)]


def _configure_sdk(host='127.0.0.1', port=8789):
    """Child-only bootstrap; no on-disk patch to Headroom or Codex."""
    _endpoint(host, port)
    import logging
    # No SDK payload/diagnostic logging. Supervisor records bounded lifecycle
    # status, and aggregate savings are persisted independently by the SDK.
    logging.disable(logging.CRITICAL)
    from dataclasses import replace
    from headroom import agent_savings
    coding = agent_savings.get_agent_savings_profile('coding')
    # 0.37's profile kwargs force-enable user compression even when the env is
    # false. The desktop applies this same in-process dataclass replacement.
    agent_savings._PROFILES['coding'] = replace(
        coding, compress_user_messages=False, compress_system_messages=False,
        effort_router=False,
    )
    agent_savings.seed_proxy_env_defaults()
    from headroom.proxy import server
    from headroom.proxy import prometheus_metrics
    # The server otherwise buffers 25 records and only flushes on graceful
    # shutdown. Windows process termination/reboot can discard an entire quiet
    # session. Restore the tracker's durable default for this local desktop:
    # every completed record uses the SDK's atomic write + fsync path.
    prometheus_metrics.PROXY_SAVINGS_FLUSH_EVERY = 1
    config = server._proxy_config_from_env()
    config.host = host
    config.port = port
    config.code_aware_enabled = True
    config.compress_user_messages = False
    config.compress_system_messages = False
    config.protect_analysis_context = True
    config.min_tokens_to_crush = 10
    config.smart_crusher_with_compaction = True
    config.target_ratio = None
    config.model_router = None
    config.log_requests = False
    config.log_file = None
    config.log_full_messages = False
    config.proxy_extensions = None
    config.rate_limit_enabled = False
    config.subscription_tracking_enabled = False
    config.compression_max_workers = 2
    _enable_recoverable_kompress()
    _enable_exact_retrieval_guard()
    _enable_responses_schema_accounting()
    return config


def _responses_schema_accounting(compress, record):
    """Repair 0.37 HTTP's message-only pair when schema savings are included.

    Only numeric counts are retained, bounded for requests without outcomes.
    WS already forms its own coherent pair; additional_tools can be counted
    inside converted messages, so neither path is widened here.
    """
    import asyncio
    from collections import OrderedDict
    from dataclasses import replace
    from functools import wraps
    from headroom.proxy.handlers.openai import _json_debug_dumps
    pending = OrderedDict()

    @wraps(compress)
    async def compressed(self, payload, **kwargs):
        # Capture classic schemas before the SDK's additional_tools lift can
        # mutate payload. Explicit timeout is the SDK's WS dispatch contract.
        tools = payload.get('tools') if isinstance(payload, dict) else None
        items = payload.get('input') if isinstance(payload, dict) else None
        if isinstance(items, list) and any(isinstance(item, dict) and item.get('type') == 'additional_tools'
                                           for item in items):
            tools = None
        result = await compress(self, payload, **kwargs)
        try:
            rid = kwargs.get('request_id')
            if tools and rid and 'timeout' not in kwargs and result[1] and result[2] > 0:
                # The SDK only returns a combined schema+router denominator.
                # This extra count must not serialize on the event loop or
                # extend forwarding by an unbounded tokenizer wait.
                def count_schema():
                    counter = self.openai_provider.get_token_counter(kwargs.get('model'))
                    return counter.count_text(_json_debug_dumps(tools))
                count = await asyncio.wait_for(asyncio.to_thread(count_schema), timeout=0.1)
                if type(count) is int and count > 0:
                    pending[rid] = count
                    pending.move_to_end(rid)
                    while len(pending) > 512:
                        pending.popitem(last=False)
        except Exception:
            pass  # Accounting cannot alter forwarding or fail a model request.
        return result

    @wraps(record)
    async def recorded(self, outcome):
        count = pending.pop(outcome.request_id, 0)
        if (count and outcome.provider == 'openai' and outcome.tokens_saved > 0
                and (outcome.tags or {}).get('endpoint') != 'responses_ws'
                and outcome.optimized_tokens == max(0, outcome.original_tokens - outcome.tokens_saved)):
            before = outcome.original_tokens + count
            if outcome.tokens_saved <= before:
                outcome = replace(outcome, original_tokens=before,
                                  optimized_tokens=before - outcome.tokens_saved)
        return await record(self, outcome)

    compressed._bundle_schema_accounting = True
    return compressed, recorded


def _enable_responses_schema_accounting():
    """Child-only, exact-wheel/contract gate; future fixed wheels stay native."""
    import inspect
    from importlib.metadata import version
    from headroom.proxy.handlers.openai import OpenAIHandlerMixin
    from headroom.proxy.server import HeadroomProxy
    method = '_compress_openai_responses_payload_in_executor'
    compress = getattr(OpenAIHandlerMixin, method)
    if getattr(compress, '_bundle_schema_accounting', False):
        return True
    if version('headroom-ai') != '0.37.0':
        return False
    try:
        source = inspect.getsource(OpenAIHandlerMixin.handle_openai_responses)
    except (OSError, TypeError):
        return False
    if ('tokenizer, original_tokens = await self._count_tokens_offloaded(model, messages)' not in source
            or 'optimized_tokens = max(0, original_tokens - tokens_saved)' not in source):
        return False
    compressed, recorded = _responses_schema_accounting(compress, HeadroomProxy._record_request_outcome)
    setattr(OpenAIHandlerMixin, method, compressed)
    HeadroomProxy._record_request_outcome = recorded
    return True


def _guard_exact_responses(original, *, root=ROOT):
    """Exclude authenticated originals from both compression and dedup.

    Responses wrappers can hide the nested MCP name, and later deltas can omit
    the originating call altogether. A locally signed result remains verifiable
    in both cases. Direct known retrieval tools retain their existing SDK policy.
    Opaque tool outputs are not interpreted as instructions or promoted in role.
    """
    from functools import wraps
    from exact_retrieval import exact_response_is_verified
    known_retrievers = {'headroom_retrieve', 'mcp__headroom_desktop__headroom_retrieve'}
    output_types = {'function_call_output', 'custom_tool_call_output', 'local_shell_call_output'}

    @wraps(original)
    def guarded(self, payload, **kwargs):
        key = 'input' if isinstance(payload.get('input'), list) else 'messages'
        items = payload.get(key)
        if not isinstance(items, list):
            return original(self, payload, **kwargs)
        retrieve_ids = {
            item.get('call_id') for item in items
            if isinstance(item, dict) and item.get('type') == 'function_call'
            and item.get('name') in known_retrievers
            and isinstance(item.get('call_id'), str) and item['call_id']
        }
        protected = {}
        for index, item in enumerate(items):
            if not isinstance(item, dict) or item.get('type') not in output_types or 'output' not in item:
                continue
            call_id = item.get('call_id')
            if not isinstance(call_id, str) or not call_id:
                continue
            if call_id in retrieve_ids or exact_response_is_verified(item['output'], root=root):
                protected[index] = item
        if not protected:
            return original(self, payload, **kwargs)

        working = dict(payload)
        working[key] = list(items)
        for index, item in protected.items():
            working[key][index] = {field: value for field, value in item.items() if field != 'output'}
        result = original(self, working, **kwargs)
        # The validated SDK adapter preserves item positions. Refuse unknown
        # result shapes rather than ever send a masked or re-compressed original.
        if not isinstance(result, tuple) or len(result) != 7 or not isinstance(result[0], dict):
            raise RuntimeError('Headroom exact-response adapter returned an unsupported result')
        updated = result[0]
        output_items = updated.get(key)
        if not isinstance(output_items, list) or len(output_items) != len(items):
            raise RuntimeError('Headroom exact-response adapter changed item positions')
        updated = dict(updated)
        updated[key] = list(output_items)
        for index, item in protected.items():
            current = output_items[index]
            if not isinstance(current, dict) or current.get('call_id') != item.get('call_id') or current.get('type') != item.get('type'):
                raise RuntimeError('Headroom exact-response adapter changed protected identity')
            updated[key][index] = item
        return (updated, *result[1:])

    guarded._desktop_exact_retrieval = True
    return guarded


def _enable_exact_retrieval_guard():
    from inspect import signature
    from headroom.proxy.handlers.openai import OpenAIHandlerMixin
    name = '_compress_openai_responses_live_text_units_with_router'
    method = getattr(OpenAIHandlerMixin, name, None)
    if not callable(method) or not {'self', 'payload', 'model', 'request_id'}.issubset(signature(method).parameters):
        raise RuntimeError('Headroom runtime lacks the exact-retrieval adapter contract')
    if not getattr(method, '_desktop_exact_retrieval', False):
        setattr(OpenAIHandlerMixin, name, _guard_exact_responses(method))


def _exact_retrieval_contract_report():
    """Exercise the selected SDK's real adapter without model traffic or ML."""
    import tempfile
    from types import SimpleNamespace
    from exact_retrieval import sign_exact_response
    from headroom.proxy.handlers.openai import OpenAIHandlerMixin
    from headroom.transforms.content_router import ContentRouter, ContentRouterConfig
    handler = OpenAIHandlerMixin()
    router = ContentRouter(ContentRouterConfig(enable_kompress=False, lossless=True))
    router._cross_turn_dedup_enabled = True
    handler.openai_pipeline = [router]
    handler.config = None
    handler.openai_provider = SimpleNamespace(
        get_token_counter=lambda model: SimpleNamespace(count_text=lambda text: len(text)))
    with tempfile.TemporaryDirectory(prefix='headroom-exact-contract-') as temp:
        root = Path(temp)
        signed = sign_exact_response('\n'.join(f'exact line {i}: preserve = {i * 17}' for i in range(100)), root=root)
        payload = {'model': 'user-selected', 'reasoning': {'effort': 'ultra'}, 'input': [
            {'type': 'custom_tool_call_output', 'call_id': 'exact-1', 'output': signed},
            {'type': 'custom_tool_call_output', 'call_id': 'exact-2', 'output': signed},
            {'type': 'function_call_output', 'call_id': 'ordinary', 'output': 'ordinary diagnostic information ' * 100},
        ]}
        before = json.dumps(payload, sort_keys=True)
        method = OpenAIHandlerMixin._compress_openai_responses_live_text_units_with_router
        result = _guard_exact_responses(method, root=root)(
            handler, payload, model='gpt-4o', request_id='local-adapter-contract')[0]
        return (result['input'][:2] == payload['input'][:2]
                and result['model'] == payload['model'] and result['reasoning'] == payload['reasoning']
                and before == json.dumps(payload, sort_keys=True))


def _write_exact_retrieval_runtime_receipt():
    """Publish serve-process proof; config/model probes never call this path."""
    import hashlib
    import tempfile
    from datetime import datetime, timezone
    from headroom.proxy.handlers.openai import OpenAIHandlerMixin
    method = OpenAIHandlerMixin._compress_openai_responses_live_text_units_with_router
    if not getattr(method, '_desktop_exact_retrieval', False):
        raise RuntimeError('Headroom exact-retrieval guard is not installed')
    state = Path(os.environ['HEADROOM_WORKSPACE_DIR'])
    if not state.is_absolute():
        raise ValueError('Managed Headroom state must be absolute')
    state.mkdir(parents=True, exist_ok=True)
    receipt = {
        'schema': 1, 'feature': 'exact-retrieval', 'protected': True,
        'pid': os.getpid(), 'loaded_at': datetime.now(timezone.utc).isoformat(),
        'source_hashes': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in ('proxy_runtime.py', 'exact_retrieval.py')},
    }
    descriptor, temporary = tempfile.mkstemp(prefix='.exact-runtime-', dir=state)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(receipt, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, state / 'exact-retrieval-runtime.json')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ExactRetrievalReceipt:
    """Publish proof only when this process actually receives network traffic."""
    def __init__(self, app):
        self.app = app
        self.recorded = False

    async def __call__(self, scope, receive, send):
        # ASGI lifespan starts before uvicorn binds. A competing process can
        # finish lifespan startup and then lose the port; it must not replace
        # the serving process's receipt. No payloads are inspected or changed.
        if not self.recorded and scope['type'] in ('http', 'websocket'):
            _write_exact_retrieval_runtime_receipt()
            self.recorded = True
        await self.app(scope, receive, send)


def _recoverable_kompress_result(compressor, result, ccr_source=None):
    """Retain every accepted lossy result only when its CCR marker pays for itself.

    Headroom 0.37 emits markers only for >=20% word savings, causing the router
    to discard smaller useful results. This is the desktop's marker-gate fix.
    Any uncertainty returns exact original content, never unrecoverable text.
    """
    if result.compressed == result.original or not compressor.config.enable_ccr:
        return result
    try:
        import tiktoken
        from headroom.transforms.kompress_compressor import ccr_retrieval_marker
        encoder = tiktoken.get_encoding('cl100k_base')
        original = ccr_source if ccr_source is not None else result.original
        key = result.cache_key
        if not key:
            key = compressor._store_in_ccr(original, result.compressed, len(original.split()))
            if not key:
                raise ValueError('CCR did not retain original')
            result.compressed += ccr_retrieval_marker(
                result.original_tokens, result.compressed_tokens, original, key)
        before = len(encoder.encode(result.original, disallowed_special=()))
        after = len(encoder.encode(result.compressed, disallowed_special=()))
        if after >= before:
            return compressor._passthrough(result.original, len(result.original.split()))
        result.cache_key = key
        result.original_tokens = before
        result.compressed_tokens = after
        result.compression_ratio = after / before
        return result
    except Exception:
        return compressor._passthrough(result.original, len(result.original.split()))


def _enable_recoverable_kompress():
    from functools import wraps
    from importlib.metadata import version
    if version('headroom-ai') != '0.37.0':
        return
    from headroom.transforms.kompress_compressor import KompressCompressor
    if getattr(KompressCompressor.compress, '_desktop_marker_gate', False):
        return
    original_compress = KompressCompressor.compress
    original_batch = KompressCompressor.compress_batch

    @wraps(original_compress)
    def compress(self, *args, **kwargs):
        return _recoverable_kompress_result(
            self, original_compress(self, *args, **kwargs), kwargs.get('ccr_original'))

    @wraps(original_batch)
    def compress_batch(self, *args, **kwargs):
        results = original_batch(self, *args, **kwargs)
        originals = kwargs.get('ccr_originals')
        return [_recoverable_kompress_result(
            self, result, originals[i] if isinstance(originals, list) and i < len(originals) else None)
            for i, result in enumerate(results)]

    compress._desktop_marker_gate = True
    KompressCompressor.compress = compress
    KompressCompressor.compress_batch = compress_batch


def _model_report():
    _configure_sdk()
    from headroom.transforms.kompress_compressor import (
        KompressCompressor, KompressConfig, KompressResult, warm_kompress_model,
    )
    from headroom.cache.compression_store import get_compression_store
    import tiktoken
    start = time.monotonic()
    ready = warm_kompress_model(allow_download=False)
    elapsed = time.monotonic() - start
    if not ready:
        return {'ok': False, 'model_ready': False, 'error': 'Local Kompress model failed to load'}
    original = ('The diagnostic report explains that the build process completed successfully. '
                'In order to provide additional background information, the following details '
                'are repeated for clarity and for reference during the investigation. '
                'The configuration uses PORT=4321 and the error identifier is ERR_TEST_123.\n') * 25
    compressor = KompressCompressor(KompressConfig())
    result = compressor.compress(original, allow_download=False)
    entry = get_compression_store().retrieve(result.cache_key) if result.cache_key else None
    exact = entry is not None and entry.original_content == original
    encoder = tiktoken.get_encoding('cl100k_base')
    before = len(encoder.encode(original))
    after = len(encoder.encode(result.compressed))
    # Exercise the old marker-gate gap independently of model variability.
    medium_original = ' '.join('diagnostic_' + str(i) for i in range(400))
    medium_compressed = ' '.join(medium_original.split()[:340])
    medium = KompressResult(compressed=medium_compressed, original=medium_original,
                            original_tokens=400, compressed_tokens=340, compression_ratio=0.85)
    medium = _recoverable_kompress_result(compressor, medium)
    medium_entry = get_compression_store().retrieve(medium.cache_key) if medium.cache_key else None
    medium_ok = medium_entry is not None and medium_entry.original_content == medium_original
    return {'ok': exact and after < before and medium_ok, 'model_ready': True,
            'load_seconds': round(elapsed, 3), 'tokens_before': before,
            'tokens_after': after, 'exact_original_recovered': exact,
            'small_saving_recovered': medium_ok, 'model': 'chopratejas/kompress-v2-base',
            'backend': 'onnx_cpu'}


def _configuration_report():
    from importlib.metadata import version
    config = _configure_sdk()
    from headroom.agent_savings import proxy_pipeline_kwargs
    from headroom.proxy.output_shaper import OutputShaperSettings, shape_responses_request
    from headroom.proxy.prometheus_metrics import PrometheusMetrics
    from headroom import paths
    pipeline = proxy_pipeline_kwargs(config)
    # The real shaper must leave model/effort/text/tool bytes unchanged when
    # disabled, including efforts the older SDK does not recognize.
    original = {'model': 'gpt-6-astra', 'reasoning': {'effort': 'ultra'},
                'instructions': 'Keep all exact instructions.',
                'input': [{'role': 'user', 'content': 'verbatim user input'}],
                'tools': []}
    before = json.dumps(original, sort_keys=True)
    shaper = OutputShaperSettings.from_env()
    shape_responses_request(original, shaper)
    preserved = before == json.dumps(original, sort_keys=True)
    exact_retrieval_protected = _exact_retrieval_contract_report()
    flush_every = PrometheusMetrics().savings_tracker._save_flush_every
    return {'ok': exact_retrieval_protected, 'version': version('headroom-ai'), 'mode': config.mode,
            'profile': config.savings_profile,
            'compress_user_messages': pipeline['compress_user_messages'],
            'compress_system_messages': pipeline['compress_system_messages'],
            'read_maturation': config.read_maturation,
            'output_shaper': shaper.enabled, 'effort_router': shaper.effort_router_enabled,
            'model_router': config.model_router is not None,
            'code_aware': config.code_aware_enabled,
            'log_requests': config.log_requests,
            'savings_flush_every': flush_every,
            'request_invariants_preserved': preserved,
            'exact_retrieval_protected': exact_retrieval_protected,
            'responses_schema_accounting': _enable_responses_schema_accounting(),
            'workspace': str(paths.workspace_dir())}


def _validate(runtime, state_dir, flag, timeout):
    """Bounded isolated SDK/config probe without sending any model request."""
    try:
        environment = build_proxy_environment(state_dir)
        if flag == '--validate-model':
            # Cold CPU inference needs more time than the production latency
            # limit. Validate model capability without changing serving policy.
            environment['HEADROOM_KOMPRESS_TIME_BUDGET_SECONDS'] = '15'
            environment['HEADROOM_KOMPRESS_ACQUIRE_TIMEOUT_SECONDS'] = '3'
        result = subprocess.run(
            [_python(runtime), str(Path(__file__).resolve()), flag],
            env=environment, cwd=str(ROOT),
            capture_output=True, text=True, encoding='utf-8', timeout=timeout,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        if result.returncode != 0:
            return {'ok': False, 'error': 'Headroom runtime validation failed',
                    'exit_code': result.returncode}
        report = json.loads(result.stdout)
        if not isinstance(report, dict) or type(report.get('ok')) is not bool:
            raise ValueError('Invalid validation report')
        if not report['ok']:
            report.setdefault('error', 'Headroom runtime validation checks failed')
        return report
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': 'Headroom runtime validation timed out'}
    except (OSError, ValueError, TypeError):
        return {'ok': False, 'error': 'Headroom runtime is unavailable or invalid'}


def validate_proxy_runtime(runtime, state_dir, timeout=45):
    return _validate(runtime, state_dir, '--validate', timeout)


def validate_proxy_model(runtime, state_dir, timeout=45):
    return _validate(runtime, state_dir, '--validate-model', timeout)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--serve', action='store_true')
    group.add_argument('--serve-transform', action='store_true')
    group.add_argument('--validate', action='store_true')
    group.add_argument('--validate-model', action='store_true')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8789)
    args = parser.parse_args(argv)
    if args.validate:
        print(json.dumps(_configuration_report()))
        return 0
    if args.validate_model:
        print(json.dumps(_model_report()))
        return 0
    if args.serve_transform:
        from request_transform_service import serve_transform
        serve_transform(ROOT, host=args.host, port=args.port)
        return 0
    config = _configure_sdk(args.host, args.port)
    from headroom.proxy import server
    create_app = server.create_app

    def create_serving_app(*args, **kwargs):
        app = create_app(*args, **kwargs)
        app.add_middleware(ExactRetrievalReceipt)
        return app

    server.create_app = create_serving_app
    try:
        server.run_server(config, workers=1, print_banner=False)
    finally:
        server.create_app = create_app
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
