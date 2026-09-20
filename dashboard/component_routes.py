"""Dashboard controls reuse the existing local Host/Origin/CSRF boundary."""
import sys
import threading
from pathlib import Path
from uuid import UUID

from flask import jsonify, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

COMPONENTS = ('rtk', 'headroom_local', 'headroom_requests', 'serena', 'local_summaries', 'llama_cpp')


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
        raise ValueError('Select a task from the list.')
    return value


def register_component_routes(app, root, security, control_factory=None, summary_factory=None, observations=None):
    root = Path(root)
    factories = {'controls': control_factory or _controls, 'summaries': summary_factory or _summaries}
    managers, lock = {}, threading.Lock()

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
            return security.error('Select a listed task and choose Refresh summary or Cancel.', 400)
        except RuntimeError:
            return security.error('Local summaries are not ready, disabled, or another job is running. Check component status.', 409)
        except Exception:
            return security.error('Local summaries are unavailable. Original conversations are unchanged.', 503)

    app.add_url_rule('/api/components', 'bundle_components', components, methods=['GET', 'POST'])
    app.add_url_rule('/api/local-summaries', 'local_summaries', summaries, methods=['GET', 'POST'])
    return snapshot
