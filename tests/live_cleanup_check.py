"""Manual Windows check: timeout cleanup stops only an owned Python fixture tree."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from service_control import ServiceController

kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel.OpenProcess.restype = wintypes.HANDLE
kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel.WaitForSingleObject.restype = wintypes.DWORD
kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel.CloseHandle.argtypes = [wintypes.HANDLE]

process = subprocess.Popen([str(root / 'dashboard/.venv/Scripts/python.exe'), '-c',
    'import os,time; print(os.getpid(),flush=True); time.sleep(60)'],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    creationflags=subprocess.CREATE_NO_WINDOW)
handle = None
try:
    child = int(process.stdout.readline().strip())
    handle = kernel.OpenProcess(0x100000 | 0x1000 | 1, False, child)
    assert handle, ctypes.get_last_error()
    result = ServiceController.cleanup_created_process(process)
    child_stopped = kernel.WaitForSingleObject(handle, 1000) == 0
    assert result['stopped'] and child_stopped, result
    evidence = {'passed': True, 'launcher_pid': process.pid, 'interpreter_pid': child,
        'interpreter_stopped': child_stopped, 'cleanup': result}
    (root / 'logs/live-cleanup-result.json').write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence))
finally:
    if handle:
        if kernel.WaitForSingleObject(handle, 0) != 0:
            kernel.TerminateProcess(handle, 1)  # Held handle for this fixture only.
        kernel.CloseHandle(handle)
    if process.poll() is None:
        process.terminate()
    process.wait(timeout=3)
