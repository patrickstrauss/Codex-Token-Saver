"""Dashboard controls reuse the existing local Host/Origin/CSRF boundary."""
import sys
import re
import threading
import os
import subprocess
from pathlib import Path
from uuid import UUID

from flask import jsonify, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

COMPONENTS = ('rtk', 'headroom_local', 'headroom_requests', 'serena', 'local_summaries', 'llama_cpp', 'playwright_cli', 'ast_grep', 'laya_router')


def _launch_disable(root):
    """Open a separate native confirmation window, never disable from HTTP."""
    script = root / 'Disable-Token-Saver.ps1'
    if sys.platform != 'win32' or not script.is_file():
        raise RuntimeError('Interactive disable is unavailable')
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    return subprocess.Popen([str(powershell), '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass',
                             '-File', str(script.resolve()), '-Interactive'],
                            cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def _controls(root):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from bundle_controls import BundleControls
    return BundleControls(root)


def _summaries(root):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from local_summaries import LocalSummaries
    return LocalSummaries(root)


def _task_id(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('Choose a local task.')
    return value


def _task_reference(value):
    """A local identifier, never a URL to fetch or a filesystem path."""
    if not isinstance(value, str) or len(value) > 128:
        raise ValueError()
    match = re.fullmatch(r'(?:codex://threads/)?([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})', value.strip())
    if not match:
        raise ValueError()
    return _task_id(match.group(1).lower())


def register_component_routes(app, root, security, control_factory=None, summary_factory=None, observations=None, hook_activity=None):
    root = Path(root).resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    factories = {'controls': control_factory or _controls, 'summaries': summary_factory or _summaries}
    managers, lock = {}, threading.Lock()
    disable_process = None

    def manager(name):
        with lock:
            if name not in managers:
                managers[name] = factories[name](root)
            return managers[name]

    def snapshot(observed=None):
        return manager('controls').status(observed if observed is not None else observations() if observations else None)

    def respond(value, code=200):
        response = jsonify(value)
        response.status_code = code
        response.headers['Cache-Control'] = 'no-store'
        return response

    def body(fields):
        request.max_content_length = 2048
        if not request.is_json:
            raise ValueError()
        payload = request.get_json()
        if not isinstance(payload, dict) or set(payload) != fields:
            raise ValueError()
        return payload

    def components():
        denied = security.guard(mutation=request.method == 'POST')
        if denied is not None:
            return denied
        if request.query_string:
            return security.error('Component controls do not accept query parameters.', 400)
        try:
            if request.method == 'POST':
                payload = body({'component', 'enabled'})
                if payload['component'] not in COMPONENTS or type(payload['enabled']) is not bool:
                    raise ValueError()
                result = manager('controls').set_enabled(payload['component'], payload['enabled'])
                current = snapshot()
                current['change'] = {'component': payload['component'], 'enabled': payload['enabled'],
                                     'restart_required': isinstance(result, dict) and result.get('restart_required') is True}
                return respond(current)
            elif observations:
                cached = (observations() or {}).get('components')
                if isinstance(cached, dict) and cached.get('components'):
                    return respond(cached)
            return respond(snapshot())
        except (ValueError, BadRequest, RequestEntityTooLarge):
            return security.error('Choose On or Off for a listed component. Refresh if its configuration changed.', 400)
        except RuntimeError:
            return security.error('This component is not ready for the change. Check its status and try again.', 409)
        except Exception:
            return security.error('Component status is unavailable. Refresh before trying another change.', 503)

    def open_disable():
        nonlocal disable_process
        denied = security.guard(mutation=True)
        if denied is not None:
            return denied
        try:
            if request.query_string or body({'action'})['action'] != 'open':
                raise ValueError()
            with lock:
                already_open = disable_process is not None and disable_process.poll() is None
                if not already_open:
                    disable_process = _launch_disable(root)
            return respond({'opened': True, 'already_open': already_open}, 202)
        except (ValueError, BadRequest, RequestEntityTooLarge):
            return security.error('Use the Disable Token Saver button to open its confirmation window.', 400)
        except Exception:
            return security.error('The disable window could not open. Run Disable-Token-Saver.cmd from the installed folder. Nothing was disabled by this request.', 503)

    def lookup_summary_task():
        denied = security.guard(mutation=False)
        if denied is not None:
            return denied
        try:
            if set(request.args) != {'task'} or len(request.args.getlist('task')) != 1:
                raise ValueError()
            task_id = _task_reference(request.args['task'])
            task = manager('summaries').lookup_task(task_id)
            if not isinstance(task, dict) or task.get('task_id') != task_id:
                return security.error('The local task lookup returned a different task. Try looking it up again.', 503)
            return respond({'task': task})
        except (ValueError, BadRequest):
            return security.error('Paste a Codex task link (codex://threads/ followed by a task ID) or a task ID only, without extra paths, queries, or fragments.', 400)
        except FileNotFoundError:
            return security.error('This task was not found on this device. Open it in Codex on this computer, then try again.', 404)
        except Exception:
            return security.error('Local task lookup is unavailable. Try again after checking the bundle status.', 503)

    def summaries():
        denied = security.guard(mutation=request.method == 'POST')
        if denied is not None:
            return denied
        try:
            if request.method == 'GET':
                if request.args:
                    if set(request.args) != {'task_id'} or len(request.args.getlist('task_id')) != 1:
                        raise ValueError()
                    return respond(manager('summaries').get_summary(_task_id(request.args['task_id'])))
                service = manager('summaries')
                return respond({'status': service.status(), 'tasks': service.list_tasks()})
            if request.query_string:
                raise ValueError()
            payload = body({'action', 'task_id'})
            if payload['action'] not in ('start', 'cancel'):
                raise ValueError()
            task_id = _task_id(payload['task_id'])
            service = manager('summaries')
            return respond(service.start(task_id) if payload['action'] == 'start' else service.cancel(task_id),
                           202 if payload['action'] == 'start' else 200)
        except (ValueError, BadRequest, RequestEntityTooLarge):
            return security.error('Look up a local task and choose Start summary or Cancel.', 400)
        except FileNotFoundError:
            return security.error('This task is no longer available locally. Look it up again in Codex.', 404)
        except RuntimeError:
            return security.error('Local summaries are not ready, disabled, or another job is running. Check component status.', 409)
        except Exception:
            return security.error('Local summaries are unavailable. Original conversations are unchanged.', 503)

    def activity():
        denied = security.guard(mutation=False)
        if denied is not None:
            return denied
        try:
            from bundle_activity import snapshot as activity_snapshot, task_titles
            if set(request.args) - {'group', 'task_id', 'limit'} or any(len(request.args.getlist(key)) != 1 for key in request.args):
                raise ValueError()
            group = request.args.get('group', 'all')
            task_id = request.args.get('task_id')
            data = activity_snapshot(root, group=group, task_id=task_id, limit=int(request.args.get('limit', '50')))
            if hook_activity:
                data['hook_coverage'] = hook_activity(task_id=data['task_id'], unknown_task=group == 'unknown')
                data['hook_coverage']['scope'] = 'unknown' if group == 'unknown' else 'task' if task_id else 'all'
                known = {task['task_id'] for task in data['tasks']}
                for hook_task in data['hook_coverage'].get('task_ids', []):
                    if hook_task not in known:
                        data['tasks'].append({'task_id': hook_task, 'count': 0, 'last_activity_at': None})
                        known.add(hook_task)
            titles = task_titles(task['task_id'] for task in data['tasks'])
            for task in data['tasks']:
                task['title'] = titles.get(task['task_id'])
            return respond(data)
        except (ValueError, BadRequest):
            return security.error('Choose a valid activity group, task ID and limit (1–200).', 400)
        except Exception:
            return security.error('Activity is unavailable. Try refreshing.', 503)

    app.add_url_rule('/api/activity', 'bundle_activity', activity, methods=['GET'])
    app.add_url_rule('/api/components', 'bundle_components', components, methods=['GET', 'POST'])
    app.add_url_rule('/api/bundle/disable', 'open_bundle_disable', open_disable, methods=['POST'])
    app.add_url_rule('/api/local-summaries', 'local_summaries', summaries, methods=['GET', 'POST'])
    app.add_url_rule('/api/local-summaries/lookup', 'lookup_summary_task', lookup_summary_task, methods=['GET'])
    return snapshot
