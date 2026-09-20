"""Local reminder preferences; status reads never start summary inference."""
import sys
import threading
from pathlib import Path

from flask import jsonify, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge


def _reminders(root):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from summary_reminders import SummaryReminders
    return SummaryReminders(root)


def register_summary_reminder_routes(app, root, security, factory=None):
    service, lock = None, threading.Lock()

    def manager():
        nonlocal service
        with lock:
            if service is None:
                service = (factory or _reminders)(Path(root))
            return service

    def reminders():
        denied = security.guard(mutation=request.method == 'POST')
        if denied is not None:
            return denied
        if request.query_string:
            return security.error('Summary reminders do not accept query parameters.', 400)
        try:
            if request.method == 'POST':
                request.max_content_length = 2048
                if not request.is_json:
                    raise ValueError()
                payload = request.get_json()
                if (not isinstance(payload, dict) or set(payload) != {'enabled', 'threshold_percent'}
                        or type(payload['enabled']) is not bool
                        or type(payload['threshold_percent']) is not int
                        or not 20 <= payload['threshold_percent'] <= 95):
                    raise ValueError()
                result = manager().configure(payload['enabled'], payload['threshold_percent'])
            else:
                result = manager().status()
            response = jsonify(result)
            response.headers['Cache-Control'] = 'no-store'
            return response
        except (ValueError, BadRequest, RequestEntityTooLarge):
            return security.error('Choose On or Off and a whole-number context threshold from 20% to 95%.', 400)
        except Exception:
            return security.error('Summary reminders are unavailable. Try reloading the panel.', 503)

    app.add_url_rule('/api/summary-reminders', 'summary_reminders', reminders, methods=['GET', 'POST'])
