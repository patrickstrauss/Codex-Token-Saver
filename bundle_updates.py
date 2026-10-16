"""Explicit, staged updates for bundled upstream components.

No network runs at import, construction, or status time. A checked release plan
stays on the server; the UI can request only check/install/rollback and a known
component. User configuration, history databases, and hook trust are untouched.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from component_runtime import COMPONENTS as OPTIONAL_COMPONENTS, component_descriptor, runtime_path, runtime_manifest

PYPI_URL = "https://pypi.org/pypi/headroom-ai/json"
GITHUB_URL = "https://api.github.com/repos/rtk-ai/rtk/releases/latest"
RTK_ASSET = "rtk-x86_64-pc-windows-msvc.zip"
SOURCES = {"headroom": "https://pypi.org/project/headroom-ai/", "rtk": "https://github.com/rtk-ai/rtk/releases",
           "serena": "https://pypi.org/project/serena-agent/", "laya": "https://pypi.org/project/laya/"}
NAMES = {"headroom": "Headroom", "rtk": "RTK", "serena": "Serena", "laya": "Laya"}
OPTIONAL_PYPI = {"serena": "https://pypi.org/pypi/serena-agent/json", "laya": "https://pypi.org/pypi/laya/json"}
METADATA_URLS = (PYPI_URL, GITHUB_URL, *OPTIONAL_PYPI.values())
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_BYTES = 80 * 1024 * 1024
MAX_BINARY_BYTES = 100 * 1024 * 1024
NETWORK_TIMEOUT = 20
PLAN_MAX_AGE = 24 * 60 * 60
SELECTION_ERROR = "The selected Headroom runtime is unavailable; the original runtime is in use."


class UpdateError(RuntimeError):
    """A user-safe operation failure; never include upstream output or secrets."""


def now():
    return datetime.now(timezone.utc).isoformat()


def stable_version(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*))?", value):
        return None
    if len(value) > 40:
        return None
    parts = tuple(int(x) for x in value.split("."))
    return parts + (0,) * (3 - len(parts))


def component_version(component, value):
    return stable_version(value)


def _component_state(key, current=None):
    return {"id": key, "name": NAMES[key], "current": current, "latest": None,
            "update_available": False, "refresh_available": False, "rollback_available": False,
            "restart_required": False, "source": SOURCES[key], "error": None}


def _official_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        return False
    if parsed.hostname in ("release-assets.githubusercontent.com", "objects.githubusercontent.com"):
        return True
    if parsed.hostname == "github.com":
        return parsed.path.startswith("/rtk-ai/rtk/releases/download/")
    return url in METADATA_URLS


class _OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        if not _official_url(newurl):
            raise UpdateError("The release download redirected outside its official hosts.")
        return super().redirect_request(request, response, code, message, headers, newurl)


def fetch_bytes(url, limit):
    if not _official_url(url):
        raise UpdateError("Only official package and release endpoints are supported.")
    request = urllib.request.Request(url, headers={"User-Agent": "CodexTokenSaver-Updater/1", "Accept": "application/json" if url in METADATA_URLS else "application/octet-stream"})
    opener = urllib.request.build_opener(_OfficialRedirect())
    try:
        with opener.open(request, timeout=NETWORK_TIMEOUT) as response:
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > limit:
                raise UpdateError("The release response exceeds the download size limit.")
            chunks, size, deadline = [], 0, time.monotonic() + 120
            while True:
                if time.monotonic() > deadline:
                    raise UpdateError("The release download timed out.")
                chunk = response.read(min(65536, limit + 1 - size))
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
                size += len(chunk)
                if size > limit:
                    raise UpdateError("The release response exceeds the download size limit.")
    except UpdateError:
        raise
    except Exception as error:
        raise UpdateError("The official release service could not be reached. Try checking again.") from error


def extract_rtk(data):
    """Inspect every ZIP path; extract only the one expected Windows executable."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 200 or sum(x.file_size for x in entries) > 2 * MAX_BINARY_BYTES:
                raise UpdateError("The RTK archive exceeds its extraction limits.")
            selected = []
            for item in entries:
                name = item.filename.replace("\\", "/")
                path = PurePosixPath(name)
                mode = item.external_attr >> 16
                if path.is_absolute() or ".." in path.parts or ":" in name or stat.S_ISLNK(mode):
                    raise UpdateError("The RTK archive contains an unsafe path or link.")
                if not item.is_dir() and path.name.lower() == "rtk.exe":
                    selected.append(item)
            if len(selected) != 1 or selected[0].file_size > MAX_BINARY_BYTES:
                raise UpdateError("The RTK archive does not contain one bounded Windows executable.")
            binary = archive.read(selected[0])
            if len(binary) > MAX_BINARY_BYTES or not binary.startswith(b"MZ"):
                raise UpdateError("The RTK download is not a Windows executable.")
            return binary
    except UpdateError:
        raise
    except Exception as error:
        raise UpdateError("The RTK release archive is corrupt or unsupported.") from error


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        # Windows readers may briefly deny replacement while polling status.
        # Keep the original intact and fail normally if access stays denied.
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if os.name != 'nt' or attempt == 4:
                    raise
                time.sleep(.01 * (attempt + 1))
    finally:
        if temporary.exists():
            temporary.unlink()


def _json_file(path, default):
    try:
        data = path.read_bytes()
        if len(data) > 256 * 1024:
            return default
        value = json.loads(data)
        return value if isinstance(value, dict) else default
    except (OSError, ValueError):
        return default


def _package_version(runtime):
    site = runtime / "Lib/site-packages"
    for metadata in site.glob("headroom*dist-info/METADATA"):
        try:
            text = metadata.read_text(encoding="utf-8")[:64 * 1024]
            name = re.search(r"(?m)^Name: (.+)$", text)
            version = re.search(r"(?m)^Version: (.+)$", text)
            if name and name[1].strip().lower().replace("_", "-") == "headroom-ai" and version and stable_version(version[1].strip()):
                return version[1].strip()
        except OSError:
            pass
    return None


class BundleUpdater:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.directory = self.root / "updates"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.state_path = self.directory / "status.json"
        self.manifest_path = self.directory / "active.json"
        self._thread = None
        self._mutex = threading.RLock()
        self._selection_diagnostic = False
        self._staged_runtimes = set()
        if not self.state_path.exists():
            handle = self._claim_lock()
            if handle:
                try:
                    if not self.state_path.exists():
                        self._write_state(self._initial_state())
                finally:
                    self._release_lock(handle)
        self._recover_interrupted()

    def _initial_state(self):
        versions = self._current_versions()
        return {"busy": False, "operation": None, "stage": "idle", "message": "Check for updates when you are ready.", "error": None,
                "last_checked": None, "plans": {}, "components": [
                    _component_state(key, versions.get(key)) for key in SOURCES]}

    def _read_state(self):
        value = _json_file(self.state_path, {})
        if not isinstance(value.get("components"), list):
            return self._initial_state()
        saved = {item.get('id'): item for item in value['components'] if isinstance(item, dict)}
        value['components'] = [dict(_component_state(key), **saved.get(key, {})) for key in SOURCES]
        value['plans'] = {key: plan for key, plan in value.get('plans', {}).items() if key in SOURCES}
        return value

    def _write_state(self, value):
        _atomic_json(self.state_path, value)

    def _claim_lock(self):
        handle = (self.directory / "operation.lock").open("a+b")
        try:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except OSError:
            handle.close()
            return None

    @staticmethod
    def _release_lock(handle):
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def _recover_interrupted(self):
        with self._mutex:
            if self._thread and self._thread.is_alive():
                return
            state = self._read_state()
            if not state.get("busy"):
                return
            handle = self._claim_lock()
            if handle:
                try:
                    state = self._read_state()
                    if not state.get("busy"):
                        return
                    state.update(busy=False, stage="interrupted", error="The previous update was interrupted. Staged files were not activated unless validation had already completed.", message="Check the installed versions before retrying.")
                    self._refresh_components(state)
                    self._write_state(state)
                finally:
                    self._release_lock(handle)

    def status(self):
        self._recover_interrupted()
        state = self._read_state()
        self._refresh_components(state)
        # Explicit allowlist prevents internal checked URLs/paths and plans from
        # becoming API response data. Messages are our own constant strings.
        fields = ("id", "name", "current", "latest", "update_available", "refresh_available", "rollback_available", "restart_required", "source", "error")
        result = {key: state.get(key) for key in ("busy", "operation", "stage", "message", "error", "last_checked", "log")}
        result["components"] = [{key: component.get(key) for key in fields} for component in state["components"]]
        # A transient status-file read failure must not make an active operation
        # look idle. The OS lock, not a persisted Boolean, is authoritative.
        handle = self._claim_lock()
        if handle:
            self._release_lock(handle)
        else:
            result["busy"] = True
        return result

    def start(self, action, component=None):
        if action not in ("check", "install", "rollback") or (action == "check" and component is not None) or (action != "check" and component not in SOURCES):
            raise ValueError("Choose check, install, or rollback for a known bundle library.")
        with self._mutex:
            handle = self._claim_lock()
            if not handle:
                raise RuntimeError("Another bundle update is already running.")
            try:
                state = self._read_state()
                if action == "install":
                    plan = state.get("plans", {}).get(component)
                    if not plan or time.time() - plan.get("checked_at", 0) > PLAN_MAX_AGE or not self._can_install(component, plan["version"]):
                        raise RuntimeError("Check for an available update before installing.")
                elif action == "rollback" and not self._rollback_available(component):
                    raise RuntimeError("No verified previous version is available for rollback.")
                state.update(busy=True, operation=action, component=component, stage="starting", message="Starting the requested update operation.", error=None,
                             log="updates/last-operation.log")
                self._write_state(state)
                self._thread = threading.Thread(target=self._job, args=(action, component, handle), daemon=True, name="bundle-update")
                self._thread.start()
            except Exception:
                self._release_lock(handle)
                raise
        return self.status()

    def _stage(self, stage, message):
        state = self._read_state()
        state.update(stage=stage, message=message)
        self._write_state(state)
        with (self.directory / "last-operation.log").open("a", encoding="utf-8") as log:
            log.write(now() + " " + stage + ": " + message + "\n")

    def _job(self, action, component, handle):
        self._staged_runtimes.clear()
        try:
            (self.directory / "last-operation.log").write_text("", encoding="utf-8")
            if action == "check":
                self._check()
            elif action == "install":
                plan = self._read_state()["plans"][component]
                getattr(self, "_install_" + component)(plan)
            else:
                getattr(self, "_rollback_" + component)()
            state = self._read_state()
            self._refresh_components(state)
            if component in ("headroom", "serena", "laya") and action in ("install", "rollback"):
                next(x for x in state["components"] if x["id"] == component)["restart_required"] = True
            state.update(busy=False, stage="complete", message="Update check complete." if action == "check" else
                         "Headroom is ready for new command workers. Restart Codex to reload existing file tools. A running desktop proxy keeps its current runtime until its next restart." if component == "headroom" else
                         "Restart Codex to load the selected Serena runtime." if component == "serena" else
                         "The selected Laya runtime is ready for the next worker. An already-running classifier retains its version until it exits." if component == "laya" else
                         "The selected library is ready for the next command.", error=None)
            self._write_state(state)
        except Exception as error:
            state = self._read_state()
            message = str(error) if isinstance(error, UpdateError) else "The update could not be completed. The active version was preserved where activation had not completed."
            state.update(busy=False, stage="failed", error=message, message="Update stopped; check the installed version and retry when ready.")
            self._refresh_components(state)
            self._write_state(state)
            with (self.directory / "last-operation.log").open("a", encoding="utf-8") as log:
                log.write(now() + " failed: " + message + "\n")
        finally:
            try:
                if action != 'check':
                    try:
                        from storage_cleanup import cleanup
                        cleanup(self.root, apply=True, lock_held=True, fresh_candidates=self._staged_runtimes)
                    except Exception:
                        # Maintenance cannot mask an update's actual result.
                        pass
            finally:
                self._release_lock(handle)

    def _current_versions(self):
        runtime = self.root / "headroom/.venv"
        headroom = _package_version(runtime)
        try:
            from runtime_selection import selected_runtime
            selected = selected_runtime(self.root, prefix=runtime)
            headroom = selected.get("version")
            self._selection_diagnostic = bool(selected.get("diagnostic"))
        except Exception:
            self._selection_diagnostic = True
        rtk = None
        try:
            result = self._run([str(self.root / "tools/rtk.exe"), "--version"], "Reading the installed RTK version failed.", timeout=10)
            match = re.search(r"\brtk\s+(\d+\.\d+(?:\.\d+)?)\b", result)
            if match and stable_version(match[1]):
                rtk = match[1]
        except (UpdateError, OSError):
            pass
        versions = {"headroom": headroom, "rtk": rtk}
        for key in OPTIONAL_COMPONENTS:
            try:
                runtime_path(self.root, key)
                versions[key] = component_descriptor(self.root, key).get('version')
            except (OSError, ValueError, KeyError):
                versions[key] = None
        return versions

    def _can_install(self, component, latest):
        current = self._current_versions().get(component)
        current, latest = component_version(component, current), component_version(component, latest)
        if latest is None:
            return False
        if current is None:
            return component in OPTIONAL_COMPONENTS
        return latest > current or ((component == "headroom" or component in OPTIONAL_COMPONENTS) and latest == current)

    def _refresh_components(self, state):
        versions = self._current_versions()
        for component in state["components"]:
            key = component["id"]
            component["current"] = versions.get(key)
            latest, current = component_version(key, component.get("latest")), component_version(key, component.get("current"))
            plan = state.get("plans", {}).get(key, {})
            fresh = bool(plan and 0 <= time.time() - plan.get("checked_at", 0) <= PLAN_MAX_AGE)
            component["update_available"] = bool(latest and fresh and ((current and latest > current) or (current is None and key in OPTIONAL_COMPONENTS)))
            component["refresh_available"] = bool((key == "headroom" or key in OPTIONAL_COMPONENTS) and latest and current and latest == current and fresh)
            component["rollback_available"] = self._rollback_available(key)
            if key == "headroom" and self._selection_diagnostic:
                component["error"] = SELECTION_ERROR
            elif key == "headroom" and component.get("error") == SELECTION_ERROR:
                component["error"] = None

    def _check(self):
        self._stage("checking", "Checking official PyPI and GitHub releases.")
        state = self._read_state()
        state["plans"] = {}
        for component in state["components"]:
            key = component["id"]
            try:
                plan = getattr(self, "_check_" + key)()
                plan["checked_at"] = time.time()
                state["plans"][key] = plan
                component.update(latest=plan["version"], error=None)
            except Exception as error:
                component.update(latest=None, error=str(error) if isinstance(error, UpdateError) else "The official release could not be checked. Try again.")
        state["last_checked"] = now()
        self._write_state(state)

    def _check_headroom(self):
        metadata = json.loads(fetch_bytes(PYPI_URL, MAX_METADATA_BYTES))
        version = metadata.get("info", {}).get("version")
        if stable_version(version) is None:
            raise UpdateError("PyPI did not return a supported stable Headroom release.")
        return {"version": version}

    def _check_rtk(self):
        release = json.loads(fetch_bytes(GITHUB_URL, MAX_METADATA_BYTES))
        tag = release.get("tag_name", "")
        version = tag[1:] if tag.startswith("v") else tag
        if stable_version(version) is None or release.get("draft") or release.get("prerelease"):
            raise UpdateError("GitHub did not return a supported stable RTK release.")
        assets = release.get("assets", [])
        found = [item for item in assets if item.get("name") == RTK_ASSET]
        if len(found) != 1:
            raise UpdateError("The RTK release has no supported Windows download.")
        digest = found[0].get("digest", "") or ""
        if re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
            return {"version": version, "tag": tag, "sha256": digest.split(":")[1].lower()}
        names = {item.get("name") for item in assets}
        checksum = next((x for x in (RTK_ASSET + ".sha256", "SHA256SUMS", "SHA256SUMS.txt", "checksums.txt", "sha256sums.txt") if x in names), None)
        if checksum is None:
            raise UpdateError("RTK cannot be installed because the official release has no SHA-256 verification.")
        data = fetch_bytes(self._asset_url(tag, checksum), 1024 * 1024).decode("utf-8-sig")
        for line in data.splitlines():
            match = re.fullmatch(r"([0-9a-fA-F]{64})(?:\s+\*?(.+))?", line.strip())
            if match and (match[2] == RTK_ASSET or (checksum == RTK_ASSET + ".sha256" and match[2] is None)):
                return {"version": version, "tag": tag, "sha256": match[1].lower()}
        raise UpdateError("The RTK checksum file did not verify the Windows download.")

    @staticmethod
    def _asset_url(tag, name):
        return "https://github.com/rtk-ai/rtk/releases/download/" + urllib.parse.quote(tag, safe="") + "/" + urllib.parse.quote(name, safe="")

    def _download_rtk(self, plan):
        if stable_version(plan.get("version")) is None or plan.get("tag") not in (plan["version"], "v" + plan["version"]) or not re.fullmatch(r"[0-9a-f]{64}", plan.get("sha256", "")):
            raise UpdateError("The checked RTK release plan is invalid. Check for updates again.")
        data = fetch_bytes(self._asset_url(plan["tag"], RTK_ASSET), MAX_ARCHIVE_BYTES)
        if hashlib.sha256(data).hexdigest() != plan["sha256"]:
            raise UpdateError("The RTK download failed SHA-256 verification; nothing was installed.")
        return extract_rtk(data)

    def _environment(self):
        environment = {key: value for key, value in os.environ.items() if not key.upper().startswith(("UV_", "PIP_", "PYTHONPATH", "PYTHONHOME"))}
        environment.update(UV_NO_CONFIG="1", UV_PYTHON_DOWNLOADS="never", UV_NO_PROGRESS="1", UV_CACHE_DIR=str(self.directory / "cache"), PIP_CONFIG_FILE=os.devnull)
        return environment

    def _baseline_python(self):
        baseline = self.root / 'headroom/.venv/Scripts/python.exe'
        version = _json_file(self.root / 'packaging/dependencies.json', {}).get('python')
        if stable_version(version) is not None and version.startswith('3.13.'):
            directory = self.root / 'tools/python'
            managed = directory / ('cpython-' + version + '-windows-x86_64-none') / 'python.exe'
            if managed.is_file() and managed.resolve().is_relative_to(directory.resolve()):
                return managed
        return baseline

    def _run(self, arguments, error_message, timeout=120, env=None):
        # Never expose subprocess output: package tooling may mention paths,
        # proxies, or credentials from the host. A bounded stage log records only
        # our messages. A file captures output without unbounded Python memory.
        with tempfile.TemporaryFile() as output:
            try:
                completed = subprocess.run(arguments, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                           cwd=self.root, env=env or self._environment(), timeout=timeout,
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0, check=False)
                if completed.returncode:
                    raise UpdateError(error_message)
                output.seek(0, 2)
                if output.tell() > 4 * 1024 * 1024:
                    raise UpdateError("A validation command exceeded its output limit.")
                output.seek(0)
                return output.read().decode("utf-8", errors="replace")
            except UpdateError:
                raise
            except subprocess.TimeoutExpired as error:
                raise UpdateError(error_message + " The operation timed out.") from error
            except OSError as error:
                raise UpdateError(error_message) from error

    def _runtime_path(self, descriptor):
        if not isinstance(descriptor, dict) or stable_version(descriptor.get("version")) is None:
            raise UpdateError("The saved Headroom runtime metadata is invalid.")
        relative = descriptor.get("runtime")
        if relative is None:
            return self.root / "headroom/.venv"
        if not isinstance(relative, str) or "\\" in relative or not re.fullmatch(r"updates/runtimes/headroom-[A-Za-z0-9.-]+", relative):
            raise UpdateError("The saved Headroom runtime is outside the managed directory.")
        resolved = (self.root / relative).resolve()
        if resolved.parent != (self.directory / "runtimes").resolve():
            raise UpdateError("The saved Headroom runtime is outside the managed directory.")
        return resolved

    def _lock_requirements(self, target, python, requirements, build_options=()):
        source = target / 'requirements.in'
        locked = target / 'requirements.txt'
        native = self.root / 'packaging/requirements-windows-runtime.txt'
        if native.is_file():
            # Fresh update venvs need the same private DLLs as a clean install.
            # Compile the fixed version/hash input into the candidate's lock.
            requirements = [*requirements, '-r "' + native.as_posix() + '"']
        source.write_text('\n'.join(requirements) + '\n', encoding='utf-8')
        self._stage('resolving_dependencies', 'Resolving compatible dependencies and package hashes from PyPI.')
        self._run([str(self.root / 'tools/uv.exe'), '--no-config', '--no-python-downloads', 'pip', 'compile',
                   str(source), '--python', str(python), '--index-url', 'https://pypi.org/simple',
                   '--generate-hashes', '--only-binary', ':all:', *build_options, '--output-file', str(locked)],
                  'Resolving the staged dependencies failed. The selected runtime is unchanged.', timeout=1800)
        content = locked.read_bytes()
        lines = (line.strip() for line in content.decode('utf-8').splitlines())
        if any(not line.startswith('#') and (' @ ' in line or '://' in line or line.startswith('-e')) for line in lines):
            raise UpdateError('A staged dependency has an unapproved direct source. Nothing was activated.')
        return locked, hashlib.sha256(content).hexdigest()

    def _stage_headroom(self, plan):
        version = plan.get("version")
        if stable_version(version) is None:
            raise UpdateError("The checked Headroom version is invalid. Check for updates again.")
        uv = self.root / "tools/uv.exe"
        baseline = self._baseline_python()
        if not uv.is_file() or not baseline.is_file():
            raise UpdateError("The bundled update runtime is missing. Repair the bundle before updating.")
        self._require_disk_space('headroom')
        target = self.directory / "runtimes" / ("headroom-" + version + "-" + uuid.uuid4().hex)
        self._staged_runtimes.add(target.relative_to(self.root).as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        self._stage("creating_runtime", "Creating an isolated Python 3.13 runtime.")
        self._run([str(uv), "--no-config", "--no-python-downloads", "venv", "--python", str(baseline), str(target)], "Creating the staged Headroom runtime failed.")
        python = target / "Scripts/python.exe"
        locked, lock_hash = self._lock_requirements(target, python, ["headroom-ai[proxy,code,mcp,reports]==" + version, "tomlkit"])
        self._stage("installing_dependencies", "Installing the checked Headroom version and its dependencies from PyPI.")
        self._run([str(uv), "--no-config", "--no-python-downloads", "pip", "install", "--python", str(python), "--index-url", "https://pypi.org/simple", "--only-binary", ":all:",
                   "--require-hashes", "-r", str(locked)], "Installing Headroom dependencies failed. The previous runtime remains active.", timeout=1800)
        self._run([str(uv), "--no-config", "--no-python-downloads", "pip", "check", "--python", str(python)], "The staged Headroom dependencies did not pass validation.", timeout=180)
        resolved = self._run([str(uv), "--no-config", "--no-python-downloads", "pip", "freeze", "--python", str(python)], "Recording the staged dependency versions failed.")
        if any(" @ " in line or "://" in line or line.startswith("-e") for line in resolved.splitlines()):
            raise UpdateError("A staged dependency uses a direct source instead of the official package index. Nothing was activated.")
        (target / "resolved-requirements.txt").write_text(resolved, encoding="utf-8")
        _atomic_json(target / "update-receipt.json", {"schema": 1, "component": "headroom", "version": version, "created_at": now(),
                     "source": SOURCES["headroom"], "index": "https://pypi.org/simple", "extras": ["proxy", "code", "mcp", "reports"],
                     "requirements": resolved.splitlines(), "lock_sha256": lock_hash, "validated": False})
        return {"version": version, "runtime": target.relative_to(self.root).as_posix()}

    def _validate_headroom(self, descriptor):
        runtime = self._runtime_path(descriptor)
        if _package_version(runtime) != descriptor["version"]:
            raise UpdateError("The staged Headroom package version does not match the checked release.")
        python = runtime / "Scripts/python.exe"
        if not python.is_file() or not (runtime / "pyvenv.cfg").is_file():
            raise UpdateError("The staged Headroom runtime is incomplete.")
        state = self.directory / "validation" / uuid.uuid4().hex
        state.mkdir(parents=True, exist_ok=True)
        current = self._current_headroom_descriptor()
        baseline_python = self.root / "headroom/.venv/Scripts/python.exe"
        self._stage("validating", "Testing both runtime launch paths and compatibility with existing cached originals.")
        script = r'''
import asyncio, importlib.metadata, json, os, re, sys
from pathlib import Path
assert sys.version_info[:2] == (3, 13), 'Python version mismatch'
from runtime_selection import activate_headroom_runtime
requested = json.loads(sys.argv[4])
selected = activate_headroom_runtime(Path.cwd(), candidate=requested)
assert not selected.get('diagnostic'), 'Runtime selection failed'
expected_runtime = (Path.cwd() / (requested['runtime'] or 'headroom/.venv')).resolve()
assert Path(selected['runtime']).resolve() == expected_runtime, 'Unexpected selected runtime'
assert Path(selected['site_packages']).resolve() == expected_runtime / 'Lib/site-packages', 'Unexpected selected packages'
assert importlib.metadata.version('headroom-ai') == sys.argv[1], 'Package version mismatch'
from command_compression import configure_offline_environment
state = Path(sys.argv[2]); configure_offline_environment(state)
import mcp, tomlkit, desktop_mcp
import headroom
assert Path(headroom.__file__).resolve().is_relative_to(expected_runtime / 'Lib/site-packages'), 'Unexpected SDK import source'
from desktop_headroom import DesktopHeadroom
backend = DesktopHeadroom(state)
def fixture(label):
    return json.dumps([{'id': i, 'status': 'CRITICAL_FAILURE_73' if i == 73 else 'OK', 'region':'ap-southeast-1', 'generation':label, 'message':'Routine request completed successfully'} for i in range(160)], indent=2) + '\r\n'
def retrieve(label):
    key = (state / (label + '.hash')).read_text()
    text = fixture(label)
    assert backend.retrieve(key, max_lines=10000).split('\n\n', 1)[1] == text, 'Cross-version retrieval mismatch'
    assert backend._get_cache().retrieve(key).original_content == text, 'Stored original mismatch'
def store(label):
    text = fixture(label)
    source = state / (label + '.json'); source.write_bytes(text.encode())
    overview = backend.read_file(str(source), max_lines=10000)
    match = re.search(r'content_hash=([0-9a-f]{24})', overview)
    assert match and 'CRITICAL_FAILURE_73' in overview, 'Compression validation failed'
    assert backend._count(overview) < backend._count(text), 'No verified reduction'
    (state / (label + '.hash')).write_text(match[1])
    retrieve(label)
phase = sys.argv[3]
if phase == 'seed': store('seed')
elif phase == 'candidate-native':
    retrieve('seed'); store('candidate-native')
elif phase == 'candidate-selected':
    retrieve('seed'); retrieve('candidate-native'); store('candidate-selected')
elif phase == 'backcheck':
    retrieve('candidate-native'); retrieve('candidate-selected')
elif phase == 'mcp':
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    async def check_mcp():
        source = state / 'mcp-fixture.json'
        text = fixture('mcp'); source.write_bytes(text.encode())
        bootstrap = "import json,runpy; from pathlib import Path; from runtime_selection import activate_headroom_runtime; "
        bootstrap += "selection=activate_headroom_runtime(Path.cwd(),candidate=" + repr(requested) + "); "
        bootstrap += "assert not selection.get('diagnostic'); runpy.run_path('desktop_mcp.py',run_name='__main__')"
        environment = dict(os.environ, HEADROOM_WORKSPACE_DIR=str(state / 'mcp-state'))
        params = StdioServerParameters(command=str(Path.cwd() / 'headroom/.venv/Scripts/python.exe'),
            args=['-u', '-c', bootstrap], env=environment, cwd=str(Path.cwd()))
        async with asyncio.timeout(40):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    assert {tool.name for tool in listing.tools} == {'headroom_read_file','headroom_retrieve','headroom_stats'}
                    assert all(tool.annotations.readOnlyHint for tool in listing.tools)
                    result = await session.call_tool('headroom_read_file', {'path':str(source),'max_lines':10000})
                    assert not result.isError
                    overview = '\n'.join(item.text for item in result.content if item.type == 'text')
                    match = re.search(r'content_hash=([0-9a-f]{24})', overview)
                    assert match and 'CRITICAL_FAILURE_73' in overview
                    exact = await session.call_tool('headroom_retrieve', {'content_hash':match[1],'max_lines':10000})
                    assert not exact.isError and exact.content[0].text.split('\n\n',1)[1] == text
                    raw = await session.call_tool('headroom_read_file', {'path':str(source),'max_lines':10000,'compress':False})
                    assert not raw.isError and raw.content[0].text.split('\n\n',1)[1] == text
                    stats = await session.call_tool('headroom_stats', {})
                    assert not stats.isError and json.loads(stats.content[0].text)['read_count'] == 2
                    first = await session.call_tool('headroom_retrieve', {'content_hash':match[1],'max_lines':1})
                    assert not first.isError and first.content[0].text.split('\n\n',1)[1] == text.splitlines(keepends=True)[0]
    asyncio.run(check_mcp())
else: raise AssertionError('Invalid validation phase')
print(json.dumps({'validated':True,'version':sys.argv[1],'phase':phase}))
'''
        environment = self._environment()
        environment.update(HEADROOM_WORKSPACE_DIR=str(state), PYTHONPATH=str(self.root), HEADROOM_OFFLINE="1", HEADROOM_TELEMETRY="off",
                           HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", TRANSFORMERS_OFFLINE="1", LITELLM_LOCAL_MODEL_COST_MAP="True",
                           TIKTOKEN_CACHE_DIR=str(self.root / "headroom/tokenizer-cache"))
        for phase, interpreter, selected in (("seed", baseline_python, current), ("candidate-native", python, descriptor),
                                             ("candidate-selected", baseline_python, descriptor), ("backcheck", baseline_python, current),
                                             ("mcp", python, descriptor)):
            result = self._run([str(interpreter), "-c", script, selected["version"], str(state), phase, json.dumps(selected)],
                               "Headroom failed runtime or cached-original compatibility validation. The previous runtime remains active.", timeout=120, env=environment)
            if not any('"validated": true' in line for line in result.splitlines()):
                raise UpdateError("Headroom validation did not produce its expected result.")
        proxy_validation = self._validate_proxy_candidate(runtime, descriptor, state)
        if descriptor.get("runtime"):
            receipt = _json_file(runtime / "update-receipt.json", {})
            phases = ["seed", "candidate-native", "candidate-selected", "backcheck", "mcp"]
            if proxy_validation:
                phases.append("proxy-config")
                if proxy_validation.get("model"):
                    phases.append("proxy-model")
                receipt["proxy_validation"] = proxy_validation
            receipt.update(validated=True, validated_at=now(), validation_phases=phases,
                           compatible_with=current["version"])
            _atomic_json(runtime / "update-receipt.json", receipt)

    def _validate_proxy_candidate(self, runtime, descriptor, state):
        """Exercise the supervisor's native launch path before selecting a runtime.

        Older bundles without the request-proxy feature keep their original
        validation. Installed proxies never silently skip a missing adapter.
        Neither probe starts routing or writes to the production savings state.
        """
        adapter = self.root / "proxy_runtime.py"
        if not adapter.is_file():
            settings = _json_file(self.root / "proxy/settings.json", {})
            if settings.get("installed") is True:
                raise UpdateError("The desktop proxy runtime adapter is missing. Repair the bundle before updating.")
            return None
        from proxy_runtime import validate_proxy_runtime, validate_proxy_model
        self._stage("validating", "Checking the staged runtime against the desktop proxy and preserved model settings.")
        expected = {"ok": True, "version": descriptor["version"], "mode": "token", "profile": "coding",
                    "compress_user_messages": False, "compress_system_messages": False,
                    "read_maturation": True, "output_shaper": False, "effort_router": False,
                    "model_router": False, "code_aware": True, "log_requests": False, "savings_flush_every": 1,
                    "request_invariants_preserved": True, "exact_retrieval_protected": True}
        report = validate_proxy_runtime(runtime, state / "proxy-config", timeout=45)
        if not isinstance(report, dict) or any(type(report.get(key)) is not type(value) or report[key] != value
                                                for key, value in expected.items()):
            raise UpdateError("Headroom failed desktop proxy compatibility validation. The previous runtime remains active.")
        result = {"configuration": expected, "adapter_sha256": hashlib.sha256(adapter.read_bytes()).hexdigest()}
        if (self.root / "models/headroom-proxy-model.json").is_file():
            self._stage("validating", "Checking local Kompress model loading, compression, and exact original recovery.")
            # Cold ONNX loading alone took 31 seconds in the captured candidate; the
            # former 45-second bound also covered SDK imports and two inference probes.
            # Keep serving limits unchanged and allow bounded cold validation headroom.
            model = validate_proxy_model(runtime, state / "proxy-model", timeout=120)
            required = ("ok", "model_ready", "exact_original_recovered", "small_saving_recovered")
            if isinstance(model, dict) and model.get("error") == "Headroom runtime validation timed out":
                raise UpdateError("Headroom local Kompress validation timed out while loading or testing its CPU model. The previous runtime remains active. Retry after heavy tasks finish.")
            if not isinstance(model, dict) or any(model.get(key) is not True for key in required):
                raise UpdateError("Headroom failed local Kompress compatibility validation. The previous runtime remains active.")
            result["model"] = {key: True for key in required}
        return result

    def _current_headroom_descriptor(self):
        from runtime_selection import selected_runtime
        baseline = self.root / "headroom/.venv"
        selected = selected_runtime(self.root, prefix=baseline)
        runtime = Path(selected["runtime"]).resolve()
        if runtime == baseline.resolve():
            return {"version": selected["version"], "runtime": None}
        descriptor = {"version": selected["version"], "runtime": runtime.relative_to(self.root).as_posix()}
        self._runtime_path(descriptor)
        return descriptor

    def _activate_headroom(self, descriptor):
        self._runtime_path(descriptor)
        current = self._current_headroom_descriptor()
        manifest = _json_file(self.manifest_path, {"schema": 1})
        backups = self.directory / "backups"
        backups.mkdir(exist_ok=True)
        _atomic_json(backups / ("headroom-manifest-" + uuid.uuid4().hex + ".json"), manifest)
        manifest["schema"] = 1
        manifest["headroom"] = dict(descriptor, previous=current) if descriptor.get("runtime") is not None else None
        manifest["headroom_previous"] = current
        self._stage("activating", "Activating the verified Headroom runtime atomically.")
        _atomic_json(self.manifest_path, manifest)

    def _install_headroom(self, plan):
        candidate = self._stage_headroom(plan)
        self._validate_headroom(candidate)
        self._activate_headroom(candidate)

    def _previous_headroom(self):
        manifest = _json_file(self.manifest_path, {})
        active = manifest.get("headroom") or {}
        return active.get("previous") or manifest.get("headroom_previous")

    def _rollback_headroom(self):
        previous = self._previous_headroom()
        if not previous:
            raise UpdateError("No previous Headroom runtime is available.")
        self._validate_headroom(previous)
        self._activate_headroom(previous)

    def _validate_rtk(self, executable, version):
        environment = self._environment()
        state = self.directory / "validation" / uuid.uuid4().hex
        state.mkdir(parents=True, exist_ok=True)
        environment.update(RTK_DB_PATH=str(state / "rtk.db"), RTK_TELEMETRY_DISABLED="1")
        output = self._run([str(executable), "--version"], "The staged RTK executable did not start.", env=environment)
        if not re.search(r"\brtk\s+" + re.escape(version) + r"(?:\s|$)", output):
            raise UpdateError("The RTK executable version does not match the checked release.")
        output = self._run([str(executable), "gain", "--all", "--format", "json"], "RTK failed its isolated statistics check.", env=environment)
        try:
            if not isinstance(json.loads(output), dict):
                raise ValueError()
        except ValueError as error:
            raise UpdateError("RTK did not return valid statistics JSON.") from error

    def _activate_rtk(self, candidate, version):
        target = self.root / "tools/rtk.exe"
        old = target.read_bytes()
        old_version = self._current_versions().get("rtk")
        if stable_version(old_version) is None:
            raise UpdateError("The installed RTK version could not be verified for rollback.")
        backups = self.directory / "backups"
        backups.mkdir(exist_ok=True)
        backup = backups / ("rtk-" + old_version + "-" + uuid.uuid4().hex + ".exe")
        backup.write_bytes(old)
        metadata = {"schema": 1, "version": version, "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                    "previous": {"version": old_version, "path": backup.relative_to(self.root).as_posix(), "sha256": hashlib.sha256(old).hexdigest()}}
        # Recovery metadata precedes the binary swap. A crash here never selects
        # it as active; version/hash checks distinguish a completed replacement.
        _atomic_json(self.directory / "rtk-pending.json", metadata)
        self._stage("activating", "Replacing RTK atomically after preserving the previous executable.")
        try:
            os.replace(candidate, target)
        except OSError as error:
            raise UpdateError("RTK is busy or could not be replaced. The previous executable remains installed; retry after commands finish.") from error
        _atomic_json(self.directory / "rtk.json", metadata)

    def _install_rtk(self, plan):
        self._stage("downloading", "Downloading the checked Windows RTK release and verifying its SHA-256 digest.")
        binary = self._download_rtk(plan)
        staged = self.directory / ("rtk-stage-" + uuid.uuid4().hex + ".exe")
        staged.write_bytes(binary)
        self._stage("validating", "Testing the verified RTK executable with an isolated statistics database.")
        self._validate_rtk(staged, plan["version"])
        self._activate_rtk(staged, plan["version"])

    def _rtk_metadata(self):
        metadata = _json_file(self.directory / "rtk.json", {})
        pending = _json_file(self.directory / "rtk-pending.json", {})
        # Recover metadata after a process died between the atomic binary swap
        # and the final metadata write; never trust an unapplied pending version.
        if pending:
            try:
                digest = hashlib.sha256((self.root / "tools/rtk.exe").read_bytes()).hexdigest()
                if pending.get("sha256") == digest:
                    return pending
            except OSError:
                pass
        return metadata

    def _rtk_backup(self):
        previous = self._rtk_metadata().get("previous")
        if not isinstance(previous, dict) or stable_version(previous.get("version")) is None:
            raise UpdateError("No valid previous RTK version is available.")
        relative = previous.get("path", "")
        if not re.fullmatch(r"updates/backups/rtk-[A-Za-z0-9.-]+\.exe", relative):
            raise UpdateError("The RTK rollback file is outside the managed backup directory.")
        path = (self.root / relative).resolve()
        if path.parent != (self.directory / "backups").resolve() or not path.is_file():
            raise UpdateError("The RTK rollback file is missing.")
        if hashlib.sha256(path.read_bytes()).hexdigest() != previous.get("sha256"):
            raise UpdateError("The RTK rollback file failed its integrity check.")
        return previous, path

    def _rollback_rtk(self):
        previous, backup = self._rtk_backup()
        staged = self.directory / ("rtk-stage-" + uuid.uuid4().hex + ".exe")
        shutil.copyfile(backup, staged)
        self._stage("validating", "Validating the preserved RTK executable before rollback.")
        self._validate_rtk(staged, previous["version"])
        self._activate_rtk(staged, previous["version"])

    def _rollback_available(self, component):
        try:
            if component in OPTIONAL_COMPONENTS:
                previous = _json_file(runtime_manifest(self.root, component), {}).get('previous')
                return bool(previous and component_version(component, previous.get('version')) and runtime_path(self.root, component, previous).is_file())
            if component == "headroom":
                previous = self._previous_headroom()
                return bool(previous and self._runtime_path(previous).is_dir())
            self._rtk_backup()
            return True
        except (UpdateError, OSError, TypeError, ValueError, KeyError):
            return False

    def _check_optional_python(self, component):
        metadata = json.loads(fetch_bytes(OPTIONAL_PYPI[component], MAX_METADATA_BYTES))
        version = metadata.get('info', {}).get('version')
        if stable_version(version) is None:
            raise UpdateError('PyPI did not return a supported stable package release.')
        return {'version': version}

    def _check_serena(self):
        return self._check_optional_python('serena')

    def _check_laya(self):
        return self._check_optional_python('laya')


    def _require_disk_space(self, component):
        minimum = (4 if component == 'laya' else 2) * 1024 ** 3
        if shutil.disk_usage(self.root).free < minimum:
            raise UpdateError('Not enough free disk space to stage this update safely. Free at least '
                              + str(minimum // 1024 ** 3) + ' GiB and retry; the active runtime is unchanged.')

    def _stage_optional_python(self, component, plan):
        version = plan.get('version')
        if stable_version(version) is None:
            raise UpdateError('The checked package version is invalid. Check again.')
        uv = self.root / 'tools/uv.exe'
        baseline = self._baseline_python()
        if not uv.is_file() or not baseline.is_file():
            raise UpdateError('The bundled update runtime is missing. Repair it before updating.')
        self._require_disk_space(component)
        base = Path(OPTIONAL_COMPONENTS[component][0]).parent
        target = self.root / base / 'runtimes' / (component + '-' + version + '-' + uuid.uuid4().hex)
        self._staged_runtimes.add(target.relative_to(self.root).as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        self._stage('creating_runtime', 'Creating an isolated optional-library runtime.')
        self._run([str(uv), '--no-config', '--no-python-downloads', 'venv', '--python', str(baseline), str(target)],
                  'Creating the isolated runtime failed.')
        python = target / 'Scripts/python.exe'
        package = OPTIONAL_COMPONENTS[component][2]
        constraints = ['transformers<5'] if component == 'laya' else []
        build_options = []
        if component == 'serena':
            # pywebview's proxy-tools dependency publishes only an sdist. All
            # other packages stay wheel-only; build it with our hashed tools.
            self._stage('installing_build_tools', 'Installing the pinned build tools in the candidate runtime.')
            self._run([str(uv), '--no-config', '--no-python-downloads', 'pip', 'install', '--python', str(python),
                       '--index-url', 'https://pypi.org/simple', '--require-hashes', '--only-binary', ':all:',
                       '-r', str(self.root / 'packaging/requirements-build.txt')],
                      'Installing the pinned build tools failed.', timeout=180)
            build_options = ['--no-binary', 'proxy-tools', '--no-build-isolation']
        locked, lock_hash = self._lock_requirements(target, python, [package + '==' + version, *constraints], build_options)
        self._stage('installing_dependencies', 'Installing the checked package version from PyPI.')
        self._run([str(uv), '--no-config', '--no-python-downloads', 'pip', 'install', '--python', str(python),
                   '--index-url', 'https://pypi.org/simple', '--only-binary', ':all:', *build_options,
                   '--require-hashes', '-r', str(locked)],
                  'Installing the staged package failed. The selected runtime is unchanged.', timeout=1800)
        self._run([str(uv), '--no-config', '--no-python-downloads', 'pip', 'check', '--python', str(python)],
                  'The staged dependencies failed validation.', timeout=180)
        frozen = self._run([str(uv), '--no-config', '--no-python-downloads', 'pip', 'freeze', '--python', str(python)],
                           'Recording dependency versions failed.')
        if any(' @ ' in line or '://' in line or line.startswith('-e') for line in frozen.splitlines()):
            raise UpdateError('A dependency has an unapproved direct source. Nothing was activated.')
        (target / 'resolved-requirements.txt').write_text(frozen, encoding='utf-8')
        _atomic_json(target / 'update-receipt.json', {'schema': 1, 'component': component, 'version': version,
                     'created_at': now(), 'source': SOURCES[component], 'index': 'https://pypi.org/simple',
                     'requirements': frozen.splitlines(), 'lock_sha256': lock_hash})
        return {'schema_version': 1, 'version': version, 'python_path': python.relative_to(self.root).as_posix()}


    def _validate_optional(self, component, descriptor):
        version = descriptor.get('version')
        if not component_version(component, version):
            raise UpdateError('The selected library version is invalid.')
        executable = runtime_path(self.root, component, descriptor)
        environment = {key: value for key, value in os.environ.items() if key.upper() in {
            'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'COMSPEC', 'TEMP', 'TMP', 'PATH',
            'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'PROGRAMDATA', 'PROGRAMFILES', 'PATHEXT'}}
        environment.update(PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                           HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false', CUDA_VISIBLE_DEVICES='')
        self._stage('validating', 'Checking the candidate library before selecting it.')
        package = OPTIONAL_COMPONENTS[component][2]
        script = 'import importlib.metadata; print(importlib.metadata.version(' + repr(package) + '))'
        actual = self._run([str(executable), '-c', script], 'The installed package version could not be verified.', env=environment)
        if actual.strip() != version:
            raise UpdateError('The candidate package version does not match the checked release.')
        if component == 'serena':
            report = json.loads(self._run([str(executable), str(self.root / 'serena_mcp.py'), '--probe-child', '--bundle-root', str(self.root)],
                                         'The Serena MCP compatibility probe failed.', timeout=90, env=environment))
            from serena_mcp import NAVIGATION_TOOLS
            if report.get('ok') is not True or set(report.get('tools', [])) != set(NAVIGATION_TOOLS):
                raise UpdateError('The candidate Serena tool list changed. Nothing was activated.')
        elif component == 'laya':
            report = json.loads(self._run([str(executable), str(self.root / 'laya_worker.py'), '--root', str(self.root), '--probe'],
                                         'The Laya offline inference compatibility probe failed.', timeout=180, env=environment))
            confidence = report.get('confidence')
            if (report.get('route') != 'symbols' or report.get('truncated') is not False
                    or type(confidence) not in (int, float) or not .55 <= confidence <= 1):
                raise UpdateError('The candidate Laya classifier did not pass real-inference qualification. Nothing was activated.')

    def _activate_optional(self, component, descriptor):
        runtime_path(self.root, component, descriptor)
        manifest = runtime_manifest(self.root, component)
        try:
            previous = component_descriptor(self.root, component)
        except (OSError, ValueError) as error:
            raise UpdateError('The existing runtime selection is invalid. Repair it before updating.') from error
        selected = dict(descriptor)
        if previous.get('version'):
            selected['previous'] = previous
        if manifest.exists():
            _atomic_json(self.directory / 'backups' / (component + '-manifest-' + uuid.uuid4().hex + '.json'),
                         _json_file(manifest, {}))
        if component == 'laya':
            model = _json_file(self.root / 'packaging/laya-model.json', {})
            if not isinstance(model.get('revision'), str):
                raise UpdateError('The Laya model manifest is unavailable.')
            # Readiness belongs to the selected runtime. Preserve the baseline
            # receipt so already-loaded older gateways can continue until reload.
            ready = runtime_path(self.root, component, descriptor).parent.parent / 'bundle-ready.json'
            _atomic_json(ready, {'version': descriptor['version'],
                         'revision': model['revision'], 'inference_verified': True})
        _atomic_json(manifest, selected)

    def _install_optional(self, component, plan):
        candidate = self._stage_optional_python(component, plan)
        self._validate_optional(component, candidate)
        self._activate_optional(component, candidate)

    def _install_serena(self, plan):
        self._install_optional('serena', plan)

    def _install_laya(self, plan):
        self._install_optional('laya', plan)


    def _rollback_optional(self, component):
        previous = _json_file(runtime_manifest(self.root, component), {}).get('previous')
        if not isinstance(previous, dict):
            raise UpdateError('There is no preserved previous runtime to restore.')
        self._validate_optional(component, previous)
        self._activate_optional(component, previous)

    def _rollback_serena(self):
        self._rollback_optional('serena')

    def _rollback_laya(self):
        self._rollback_optional('laya')
