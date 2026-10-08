"""Mandatory Laya authorization for explicit bundle operations.

Public MCP calls never infer caller identity or authorization from startup env.
Already-routed Python workers use routed_call(root, component); private child
entry points may translate the router-owned CTS_LAYA_INTERNAL marker into that
context. Typed requests dispatch deterministically; only natural-language
bundle_query uses neural classification. Automatic compression/hooks stay fast.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path
import re
import sys

import bundle_router
from bundle_preferences import load_preferences


OPERATIONS = {
    'headroom_local': frozenset(('headroom_read_file', 'headroom_retrieve', 'headroom_stats', 'command_output')),
    'serena': frozenset(('activate_project', 'get_symbols_overview', 'find_symbol', 'find_referencing_symbols')),
    'ast_grep': frozenset(('run', 'scan', 'rewrite', 'test', 'new', 'lsp', 'completions')),
    'playwright_cli': frozenset(('attach', 'detach', 'open', 'close', 'close-all', 'kill-all', 'list',
        'goto', 'go-back', 'go-forward', 'reload', 'snapshot', 'click', 'dblclick', 'hover', 'drag',
        'type', 'fill', 'press', 'keydown', 'keyup', 'select', 'check', 'uncheck', 'upload', 'resize',
        'screenshot', 'pdf', 'eval', 'run-code', 'tab-list', 'tab-new', 'tab-close', 'tab-select',
        'dialog-accept', 'dialog-dismiss', 'console', 'network', 'route', 'route-list', 'unroute',
        'state-save', 'state-load', 'cookie-list', 'cookie-get', 'cookie-set', 'cookie-delete', 'cookie-clear',
        'localstorage-list', 'localstorage-get', 'localstorage-set', 'localstorage-delete', 'localstorage-clear',
        'sessionstorage-list', 'sessionstorage-get', 'sessionstorage-set', 'sessionstorage-delete', 'sessionstorage-clear',
        'tracing-start', 'tracing-stop', 'video-start', 'video-stop', 'install', 'install-browser',
        'find', 'drop', 'delete-data', 'mousemove', 'mousedown', 'mouseup', 'mousewheel',
        'set-color-scheme', 'set-reduced-motion', 'set-forced-colors', 'set-contrast', 'set-media',
        'clear-color-scheme', 'clear-reduced-motion', 'clear-forced-colors', 'clear-contrast', 'clear-media',
        'requests', 'request', 'request-headers', 'request-body', 'response-headers', 'response-body',
        'network-state-set', 'recording-start', 'recording-stop', 'video-chapter', 'video-show-actions',
        'video-hide-actions', 'show', 'pause-at', 'resume', 'step-over', 'generate-locator', 'highlight',
        'webmcp-list', 'webmcp-call')),
    # RTK's native command parser validates command arguments after this family gate.
    'rtk': frozenset(('command', 'git', 'rg')),
}
CLI_COMPONENTS = frozenset(('ast_grep', 'playwright_cli', 'rtk'))
INFORMATIONAL_OPERATIONS = frozenset((('headroom_local', 'headroom_stats'),))
_routed = ContextVar('cts_laya_routed', default=None)
_UUID = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}')


class AuthorizationError(RuntimeError):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


def _task_id(value):
    return value.lower() if isinstance(value, str) and _UUID.fullmatch(value) else None


def _operation_kind(component, operation):
    return ('informational' if isinstance(component, str) and isinstance(operation, str)
            and (component, operation) in INFORMATIONAL_OPERATIONS else 'operation')


def record_activity(root, component, outcome, *, task_id=None, kind='operation', error_code=None):
    """Telemetry cannot discard completed work or expose free-form error text."""
    if os.environ.get('CTS_ACTIVITY_KIND') == 'diagnostic':
        kind = 'diagnostic'
    try:
        from bundle_activity import record
        record(root, component, outcome, task_id=_task_id(task_id), kind=kind, error_code=error_code)
    except (ImportError, OSError, ValueError, RuntimeError):
        pass


@contextmanager
def routed_call(root, component):
    """Private, process-local scope for a component the router already selected."""
    token = _routed.set((Path(root).resolve(), component))
    try:
        yield
    finally:
        _routed.reset(token)


def _record_routing(root, outcome, component, elapsed_ms=None, *, task_id=None, kind='operation'):
    if kind == 'informational':
        # Metadata queries are visible without inflating actual-work counters.
        record_activity(root, 'laya_router', outcome, task_id=task_id, kind=kind)
        return
    try:
        bundle_router.record(root, outcome, ['laya', component], elapsed_ms, task_id=task_id)
    except (ImportError, OSError, ValueError, RuntimeError):
        pass


def _recover_original(root, route, explanation, *, task_id=None):
    # Deterministic recovery is restricted to the fixed cached-original operation.
    record_activity(root, 'laya_router', 'bypassed', task_id=task_id,
                    kind='operation', error_code='disabled')
    return {'route': route, 'exact': True, 'status': 'retrieval_recovery',
            'notice': 'Laya retrieval recovery: ' + explanation + '; deterministic routing returned exact stored original text.'}


def authorize_explicit(root, component, operation, *, task_id=None):
    """Return route/exact/status/notice, or fail closed before tool execution.

    The caller has already selected a typed tool. Validate its component and
    operation, enforce live toggles, and record that deterministic routing choice.
    No neural inference, invented confidence, or raw-argument logging occurs.
    """
    root = Path(root).resolve()
    task_id = _task_id(task_id)
    try:
        if not isinstance(component, str) or not isinstance(operation, str):
            raise AuthorizationError('Unknown explicit Token Saver operation; no tool executed.', 'invalid_input')
        route = next((key for key, value in bundle_router.COMPONENT.items() if value == component), None)
        operation = operation.split(maxsplit=1)[0] if component in CLI_COMPONENTS and operation.strip() else operation
        if not route or operation not in OPERATIONS.get(component, ()):
            raise AuthorizationError('Unknown explicit Token Saver operation; no tool executed.', 'invalid_input')
        exact_original = component == 'headroom_local' and operation == 'headroom_retrieve'
        # Process markers apply only to the short-lived CLI families. Shared MCP
        # families never interpret them here; Serena consumes its private marker
        # in its launcher and uses a component-scoped ContextVar instead.
        internal_cli = component in CLI_COMPONENTS and os.environ.get('CTS_LAYA_INTERNAL') == '1'
        if _routed.get() == (root, component) or internal_cli:
            return {'route': route, 'exact': exact_original, 'status': 'already_routed', 'notice': None}
        preferences = load_preferences(root)
        if not preferences['laya_router']:
            if exact_original:
                return _recover_original(root, route, 'router is Off', task_id=task_id)
            raise AuthorizationError('Laya router is Off. Explicit Token Saver operations require Laya On.', 'disabled')
        if not preferences[component]:
            if exact_original:
                return _recover_original(root, route, 'Headroom is Off', task_id=task_id)
            raise AuthorizationError('Requested Token Saver component is Off; no tool executed.', 'disabled')
        _record_routing(root, 'completed', component, 0, task_id=task_id,
                        kind=_operation_kind(component, operation))
        return {'route': route, 'exact': exact_original, 'status': 'typed_route', 'notice': None}
    except AuthorizationError:
        # The caller records the component outcome. This is one router event,
        # avoiding duplicate component failures when a CLI also logs its result.
        if component in bundle_router.COMPONENT.values():
            _record_routing(root, 'blocked', component, task_id=task_id,
                            kind=_operation_kind(component, operation))
        raise


@contextmanager
def explicit_call(root, component, operation, *, task_id=None):
    """Authorize then record the actual tool outcome (never its arguments)."""
    task_id = _task_id(task_id)
    kind = _operation_kind(component, operation)
    try:
        authorization = authorize_explicit(root, component, operation, task_id=task_id)
    except AuthorizationError as exc:
        record_activity(root, component, 'blocked', task_id=task_id, kind=kind, error_code=exc.code)
        raise
    # The routed parent owns attribution and the single component ledger event.
    # Child backends may still maintain their existing aggregate statistics.
    owns_event = authorization['status'] != 'already_routed'
    try:
        yield authorization
    except Exception:
        if owns_event:
            record_activity(root, component, 'failed', task_id=task_id, kind=kind, error_code='execution_failed')
        raise
    else:
        if owns_event:
            record_activity(root, component, 'completed', task_id=task_id, kind=kind)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--authorize', choices=['rtk'])
    mode.add_argument('--record-rtk', type=int, metavar='EXIT')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    task_id = _task_id(os.environ.get('CODEX_THREAD_ID'))
    if args.record_rtk is not None:
        record_activity(root, 'rtk', 'completed' if args.record_rtk == 0 else 'failed',
                        task_id=task_id,
                        kind='diagnostic' if os.environ.get('CTS_ACTIVITY_KIND') == 'diagnostic' else 'operation',
                        error_code=None if args.record_rtk == 0 else 'nonzero_exit')
        return 0
    try:
        # This short-lived CLI has a caller-owned environment, unlike shared MCP.
        # --authorize is an external authorization boundary, never a routed child
        # execution. Inherited markers must not bypass its live toggle checks.
        os.environ.pop('CTS_LAYA_INTERNAL', None)
        authorize_explicit(root, args.authorize, 'command', task_id=task_id)
    except AuthorizationError as exc:
        print(str(exc), file=sys.stderr)
        return 126
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
