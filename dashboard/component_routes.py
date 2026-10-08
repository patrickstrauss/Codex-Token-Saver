"""Dashboard controls reuse the existing local Host/Origin/CSRF boundary."""
import sys
import threading
import os
import subprocess
from pathlib import Path

from flask import jsonify, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

COMPONENTS = ('rtk', 'headroom_local', 'headroom_requests', 'serena', 'playwright_cli', 'ast_grep', 'laya_router')


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








def register_component_routes(app, root, security, control_factory=None, observations=None, hook_activity=None):
    root = Path(root).resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    controls, lock = None, threading.Lock()
    disable_process = None

    def manager():
        nonlocal controls
        with lock:
            if controls is None:
                controls = (control_factory or _controls)(root)
            return controls

    def snapshot(observed=None):
        return manager().status(observed if observed is not None else observations() if observations else None)

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
                result = manager().set_enabled(payload['component'], payload['enabled'])
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
    return snapshot
