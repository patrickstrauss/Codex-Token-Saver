"""A dashboard must survive closing the terminal/Codex job that started it."""
import ctypes
from ctypes import wintypes as win
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows job lifetime contract')
class ServiceLifetimeTests(unittest.TestCase):
    def test_dashboard_survives_starter_job_closure(self):
        class Limits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                        ('flags', win.DWORD), ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t),
                        ('active', win.DWORD), ('affinity', ctypes.c_size_t),
                        ('priority', win.DWORD), ('scheduling', win.DWORD)]
        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('basic', Limits), ('io', ctypes.c_ulonglong * 6),
                        ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, win.LPCWSTR]
        kernel.CreateJobObjectW.restype = win.HANDLE
        kernel.SetInformationJobObject.argtypes = [win.HANDLE, ctypes.c_int, ctypes.c_void_p, win.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [win.HANDLE, win.HANDLE]
        kernel.CloseHandle.argtypes = [win.HANDLE]
        kernel.OpenProcess.argtypes = [win.DWORD, win.BOOL, win.DWORD]
        kernel.OpenProcess.restype = win.HANDLE
        kernel.WaitForSingleObject.argtypes = [win.HANDLE, win.DWORD]
        job = kernel.CreateJobObjectW(None, None)
        self.assertTrue(job)
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000 | 0x800  # KILL_ON_JOB_CLOSE | BREAKAWAY_OK
        self.assertTrue(kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        with tempfile.TemporaryDirectory(prefix='CTS service lifetime ') as folder:
            root = Path(folder)
            dashboard = root / 'dashboard'
            runtime = dashboard / '.venv/Scripts/python.exe'
            runtime.parent.mkdir(parents=True)
            runtime.touch()
            nonce = root.name
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            (dashboard / 'app.py').write_text('''
import json, os, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(json.dumps({'service':'codex-token-saver-dashboard','status':'ok',
                                    'fixture':os.environ['CTS_FIXTURE']}).encode())
    def do_POST(self):
        self.send_response(200); self.end_headers()
        threading.Thread(target=self.server.shutdown,daemon=True).start()
    def log_message(self,*args): pass
server=HTTPServer(('127.0.0.1',int(os.environ['PORT'])),Handler)
server.serve_forever(); server.server_close()
''')
            (root / 'starter.py').write_text('''
import json, os, sys, time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import service_control
input()  # The test assigns this process to its disposable job first.
original=service_control.subprocess.Popen
def launch(command,**kwargs):
    command[0]=sys.argv[4]
    return original(command,**kwargs)
service_control.subprocess.Popen=launch
control=service_control.ServiceController(Path(sys.argv[2]))
control.ports['dashboard']=int(sys.argv[3])
print(json.dumps(control.ensure('dashboard')),flush=True)
time.sleep(60)
''')
            parent = subprocess.Popen([sys._base_executable, str(root/'starter.py'), str(ROOT), str(root), str(port), sys.executable],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env=dict(os.environ, CTS_FIXTURE=nonce), creationflags=subprocess.CREATE_NO_WINDOW)
            endpoint = f'http://127.0.0.1:{port}/health'
            child_handle = None
            try:
                self.assertTrue(kernel.AssignProcessToJobObject(job, win.HANDLE(int(parent._handle))))
                parent.stdin.write('go\n'); parent.stdin.flush()
                ready = json.loads(parent.stdout.readline())
                self.assertTrue(ready['ready'], ready)
                child_handle = kernel.OpenProcess(0x100000, False, ready['pid'])  # SYNCHRONIZE
                self.assertTrue(child_handle)
                kernel.CloseHandle(job); job = None
                parent.wait(timeout=5)
                try:
                    with urlopen(endpoint, timeout=2) as response:
                        alive = json.load(response).get('fixture') == nonce
                except OSError:
                    alive = False
                self.assertTrue(alive, 'Closing the starter job also killed its dashboard')
            finally:
                if job:
                    kernel.CloseHandle(job)
                if parent.poll() is None:
                    parent.terminate(); parent.wait(timeout=5)
                try:
                    with urlopen(endpoint, timeout=1) as response:
                        owned = json.load(response).get('fixture') == nonce
                    if owned:
                        with urlopen(Request(endpoint, data=b'stop', method='POST'), timeout=2):
                            pass
                except OSError:
                    pass
                if child_handle:
                    stopped = kernel.WaitForSingleObject(child_handle, 5000)
                    kernel.CloseHandle(child_handle)
                    self.assertEqual(stopped, 0, 'Disposable dashboard did not stop')
                for stream in (parent.stdin,parent.stdout,parent.stderr):
                    stream.close()
