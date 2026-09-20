"""Loopback-only, explicitly requested library update operations."""
import secrets
import sys
import threading
from pathlib import Path

from flask import Response, jsonify, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge


def _make_updater(root):
    # The installed bundle is a sibling of the dashboard, never supplied by a request.
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from bundle_updates import BundleUpdater
    return BundleUpdater(root)


class UpdateRoutes:
    def __init__(self, root, port, versions, factory):
        self.root = Path(root)
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.versions = versions
        self.factory = factory
        self.csrf_token = secrets.token_urlsafe(32)
        self._updater = None
        self._lock = threading.Lock()

    def guard(self, mutation=False):
        origin = request.headers.get("Origin")
        if (request.scheme != "http" or request.host.lower() not in self.allowed_hosts
                or request.headers.get("Sec-Fetch-Site") == "cross-site"
                or (origin is not None and origin != f"http://{request.host}")
                or (mutation and not origin)):
            return self.error("Open the dashboard from its local address to manage updates.", 403)
        if mutation and not secrets.compare_digest(
                request.headers.get("X-Codex-Update-Token", "").encode("utf-8"),
                self.csrf_token.encode("ascii")):
            return self.error("Refresh this dashboard page before managing updates.", 403)
        return None

    @staticmethod
    def error(message, status):
        response = jsonify({"error": message})
        response.status_code = status
        response.headers["Cache-Control"] = "no-store"
        return response

    def manager(self):
        with self._lock:
            if self._updater is None:
                self._updater = self.factory(self.root)
            return self._updater

    def snapshot_response(self, snapshot, status=200):
        if not snapshot.get("busy"):
            for component in snapshot.get("components", []):
                if component.get("id") == "rtk" and isinstance(component.get("current"), str):
                    self.versions["rtk"] = component["current"]
        response = jsonify(snapshot)
        response.status_code = status
        response.headers["Cache-Control"] = "no-store"
        return response

    def page(self, html):
        denied = self.guard()
        if denied is not None:
            return denied
        response = Response(html.replace("__BUNDLE_UPDATE_CSRF__", self.csrf_token), mimetype="text/html")
        response.headers.update({"Cache-Control": "no-store", "X-Frame-Options": "DENY",
                                 "Referrer-Policy": "no-referrer"})
        return response

    def handle(self):
        denied = self.guard(mutation=request.method == "POST")
        if denied is not None:
            return denied
        if request.query_string:
            return self.error("Update requests do not accept query parameters.", 400)
        if request.method == "GET":
            try:
                return self.snapshot_response(self.manager().status())
            except Exception:
                return self.error("Update status is unavailable. Try again shortly.", 503)
        try:
            request.max_content_length = 2048
            if not request.is_json:
                raise ValueError()
            payload = request.get_json()
            if not isinstance(payload, dict) or set(payload) - {"action", "component"}:
                raise ValueError()
            action, component = payload.get("action"), payload.get("component")
            if action == "check":
                if "component" in payload:
                    raise ValueError()
            elif action in ("install", "rollback"):
                if component not in ("headroom", "rtk"):
                    raise ValueError()
            else:
                raise ValueError()
        except (ValueError, BadRequest, RequestEntityTooLarge):
            return self.error("Choose Check for updates, Update, or Rollback for a listed library.", 400)
        try:
            return self.snapshot_response(self.manager().start(action, component), 202)
        except ValueError:
            return self.error("This update request is not valid. Refresh the library status.", 400)
        except RuntimeError:
            return self.error("Another update is running, or no checked update is available. Refresh the status and try again.", 409)
        except Exception:
            return self.error("The update could not start. Refresh the status before trying again.", 503)


def register_update_routes(app, root, port, versions, updater_factory=None):
    updates = UpdateRoutes(root, port, versions, updater_factory or _make_updater)
    app.add_url_rule("/api/updates", "library_updates", updates.handle, methods=["GET", "POST"])
    return updates
