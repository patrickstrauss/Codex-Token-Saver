"""Exercise the bundled CLI against a disposable, hidden Electron renderer."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


def verify(root, electron):
    with tempfile.TemporaryDirectory(prefix='CTS Electron fixture ') as folder:
        directory = Path(folder)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        (directory / 'index.html').write_text('<title>CTS disposable fixture</title><button onclick="document.querySelector(\'#count\').textContent=Number(document.querySelector(\'#count\').textContent)+1">Increment</button><output id="count">0</output>')
        (directory / 'main.cjs').write_text('''
const {app, BrowserWindow} = require('electron');
const fs = require('fs');
app.setPath('userData', __dirname + '/profile');
app.commandLine.appendSwitch('remote-debugging-address', '127.0.0.1');
app.commandLine.appendSwitch('remote-debugging-port', process.argv[2]);
app.whenReady().then(async () => {
  const window = new BrowserWindow({show:false, webPreferences:{contextIsolation:true, nodeIntegration:false}});
  await window.loadFile(__dirname + '/index.html');
  fs.writeFileSync(__dirname + '/ready', 'ok');
});
setInterval(() => { if(fs.existsSync(__dirname + '/stop')) app.quit(); }, 200);
setTimeout(() => app.quit(), 120000);
''')
        environment = dict(os.environ)
        environment['CTS_ACTIVITY_KIND'] = 'diagnostic'
        environment.pop('ELECTRON_RUN_AS_NODE', None)
        environment['PLAYWRIGHT_BROWSERS_PATH'] = str(root / 'tools/playwright-browsers')
        session = 'cts-electron-' + str(port)
        def cli(*args):
            result = subprocess.run([str(root / 'bin/playwright-cli.exe'), '-s=' + session, *args],
                                    cwd=directory, env=environment, capture_output=True, text=True,
                                    encoding='utf-8', timeout=40)
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            return result.stdout
        with (directory / 'electron.log').open('w') as log:
            app = subprocess.Popen([str(electron), str(directory / 'main.cjs'), str(port)], cwd=directory,
                                   env=environment, stdout=log, stderr=log,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                deadline = time.monotonic() + 30
                while not (directory / 'ready').exists():
                    if app.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('Disposable Electron did not start.')
                    time.sleep(.2)
                attached = cli('attach', '--cdp=http://127.0.0.1:' + str(port))
                snapshot = cli('snapshot')
                assert 'Increment' in snapshot, snapshot
                cli('run-code', "async page => { await page.getByRole('button', {name:'Increment'}).click(); }")
                result = cli('eval', '() => document.querySelector("#count").textContent')
                assert '"1"' in result, result
                cli('detach')
                assert app.poll() is None, 'Detach unexpectedly stopped the external Electron app.'
                evidence = {'electron_version': subprocess.check_output([str(electron), '--version'], env=environment, text=True).strip(),
                            'attached': True, 'snapshot': True, 'click_result': 1, 'detach_preserved_app': True,
                            'scope': 'hidden disposable renderer; no user app was restarted'}
                print(json.dumps(evidence))
                return evidence
            finally:
                (directory / 'stop').touch()
                try:
                    app.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    app.terminate()  # Only the fixture child created by this test.
                    app.wait(timeout=10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--electron', type=Path, required=True)
    args = parser.parse_args()
    verify(args.root.resolve(), args.electron.resolve())
