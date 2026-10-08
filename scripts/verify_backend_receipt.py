"""Exercise competing backend launches on an isolated port and temporary state."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from proxy_runtime import build_proxy_command, build_proxy_environment


def _windows_job(process):
    """The fixture also exits if this CLI is cancelled or crashes."""
    if os.name != 'nt':
        return lambda: None
    import ctypes
    from ctypes import wintypes as w

    class Basic(ctypes.Structure):
        _fields_ = [('ProcessTime', ctypes.c_longlong), ('JobTime', ctypes.c_longlong),
                    ('Flags', w.DWORD), ('MinWorkingSet', ctypes.c_size_t),
                    ('MaxWorkingSet', ctypes.c_size_t), ('ActiveLimit', w.DWORD),
                    ('Affinity', ctypes.c_size_t), ('Priority', w.DWORD), ('Scheduling', w.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [('Basic', Basic), ('IO', ctypes.c_ulonglong * 6),
                    ('ProcessMemory', ctypes.c_size_t), ('JobMemory', ctypes.c_size_t),
                    ('PeakProcessMemory', ctypes.c_size_t), ('PeakJobMemory', ctypes.c_size_t)]

    class Accounting(ctypes.Structure):
        _fields_ = [('TotalUserTime', ctypes.c_longlong), ('TotalKernelTime', ctypes.c_longlong),
                    ('ThisPeriodTotalUserTime', ctypes.c_longlong), ('ThisPeriodTotalKernelTime', ctypes.c_longlong),
                    ('TotalPageFaultCount', w.DWORD), ('TotalProcesses', w.DWORD),
                    ('ActiveProcesses', w.DWORD), ('TotalTerminatedProcesses', w.DWORD)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
    kernel.TerminateJobObject.restype = w.BOOL
    kernel.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    kernel.QueryInformationJobObject.restype = w.BOOL
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.WaitForSingleObject.restype = w.DWORD
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    info = Extended()
    info.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if (not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)) or
            not kernel.AssignProcessToJobObject(handle, w.HANDLE(int(process._handle)))):
        if handle:
            kernel.CloseHandle(handle)
        raise RuntimeError('Could not establish fixture process cleanup')
    def close():
        nonlocal handle
        if not handle:
            return
        owned_handles = []
        try:
            # ActiveProcesses can reach zero before process handles are signaled.
            # Retain handles for this job's current members to verify actual exit too.
            capacity = 16
            while True:
                class ProcessIds(ctypes.Structure):
                    _fields_ = [('Assigned', w.DWORD), ('Listed', w.DWORD),
                                ('Ids', ctypes.c_size_t * capacity)]
                members = ProcessIds()
                if kernel.QueryInformationJobObject(handle, 3, ctypes.byref(members), ctypes.sizeof(members), None):
                    break  # JobObjectBasicProcessIdList = 3
                if ctypes.get_last_error() != 234 or capacity >= 65536:  # ERROR_MORE_DATA
                    raise RuntimeError('Could not list owned fixture processes for cleanup')
                capacity = min(65536, max(capacity * 2, members.Assigned))
            for pid in members.Ids[:members.Listed]:
                member = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
                if member:
                    owned_handles.append(member)
                elif ctypes.get_last_error() != 87:  # ERROR_INVALID_PARAMETER: already exited
                    raise RuntimeError('Could not wait for an owned fixture process')
            if not kernel.TerminateJobObject(handle, 1):
                raise RuntimeError('Could not terminate owned fixture processes')
            deadline = time.monotonic() + 10
            accounting = Accounting()
            while True:
                # JobObjectBasicAccountingInformation = 1, includes all descendants.
                if not kernel.QueryInformationJobObject(handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None):
                    raise RuntimeError('Could not verify owned fixture process cleanup')
                if not accounting.ActiveProcesses:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('Owned fixture processes did not exit before cleanup deadline')
                time.sleep(.05)
            for member in owned_handles:
                remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                if kernel.WaitForSingleObject(member, remaining_ms) != 0:
                    raise TimeoutError('An owned fixture process did not finish exiting')
        finally:
            for member in owned_handles:
                kernel.CloseHandle(member)
            kernel.CloseHandle(handle)
            handle = None
    return close

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path)
    args = parser.parse_args()
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
    opener = build_opener(ProxyHandler({}))
    with tempfile.TemporaryDirectory(prefix='headroom-serving-proof-') as temporary:
        state = Path(temporary)
        assert state.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
        command = build_proxy_command(args.runtime, port=port)
        env = build_proxy_environment(state)
        processes, closers = [], []
        with (state / 'test.log').open('wb') as log:
            def launch():
                process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=log,
                                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                processes.append(process)
                closers.append(_windows_job(process))
                return process
            try:
                owner = launch()
                deadline = time.monotonic() + 40
                while True:
                    if owner.poll() is not None:
                        raise RuntimeError('Isolated backend exited before readiness')
                    try:
                        with opener.open(f'http://127.0.0.1:{port}/health', timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        pass
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Isolated backend did not become ready')
                    time.sleep(0.1)
                receipt = state / 'exact-retrieval-runtime.json'
                before = receipt.read_bytes()
                proof = json.loads(before)
                assert proof['protected'] is True
                assert all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == value
                           for name, value in proof['source_hashes'].items())
                duplicate = launch()
                assert duplicate.wait(timeout=30) != 0, 'Duplicate unexpectedly acquired occupied port'
                assert receipt.read_bytes() == before, 'Failed duplicate replaced the serving receipt'
                assert owner.poll() is None
                with opener.open(f'http://127.0.0.1:{port}/health', timeout=2) as response:
                    assert response.status == 200
            finally:
                for close in reversed(closers):
                    close()
                for process in processes:
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=10)
        # Job termination is asynchronous: the Windows venv redirector can
        # exit just before its child releases the inherited log handle.
        deadline = time.monotonic() + 5
        while True:
            try:
                (state / 'test.log').unlink()
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
    print(json.dumps({'ok': True, 'ready_backend_published_proof': True,
                      'failed_duplicate_preserved_proof': True,
                      'serving_backend_unchanged': True, 'isolated_state': True,
                      'temporary_state_removed': True}))


if __name__ == '__main__':
    main()
