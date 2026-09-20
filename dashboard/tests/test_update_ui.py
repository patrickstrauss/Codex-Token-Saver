"""Run the shipped update controller with an isolated DOM and scripted responses."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Requires Node for shipped JavaScript')
def test_manual_checks_component_selection_progress_and_no_error_replay():
    script = (Path(__file__).parents[1] / 'static' / 'updates.js').read_text(encoding='utf-8')
    harness = r'''
const vm = require('node:vm');
const source = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const nodes = {}, calls = [], responses = [], timers = [];
function node(id) { return nodes[id] ||= {textContent: '', hidden: false, disabled: false, open: false, listeners: {},
    addEventListener(type, fn) { this.listeners[type] = fn; }}; }
const idle = {busy: false, stage: 'ready', message: 'Ready', log: 'updates/last-operation.log', components: [
    {id:'headroom',current:'0.37.0',latest:'0.37.0',update_available:false,refresh_available:true,rollback_available:true},
    {id:'rtk',current:'0.49.0',latest:'0.50.0',update_available:true,rollback_available:false}]};
const context = {document: {getElementById: node, querySelector: () => ({content: 'csrf-fixture'})},
    setInterval(fn) { timers.push(fn); }, fetch: async (url, opts={}) => {
        calls.push({url, ...opts});
        const reply = responses.shift();
        if (!reply) throw new Error('Unexpected request');
        return {ok: reply.ok !== false, json: async () => reply.data};
    }};
vm.createContext(context);
vm.runInContext(source, context);
async function flush() { for (let i=0;i<8;i++) await Promise.resolve(); }
(async () => {
    await timers[0](); await flush();
    const startupCalls = calls.length;
    responses.push({data: idle});
    node('library-updates').open = true;
    node('library-updates').listeners.toggle(); await flush();
    const opened = {calls: calls.length, current: node('update-headroom-current').textContent,
        latest: node('update-headroom-latest').textContent, canUpdate: !node('update-headroom-install').disabled,
        updateLabel: node('update-headroom-install').textContent, log: node('updates-log').textContent};
    responses.push({data: {...idle, busy: true, stage: 'checking', message: 'Checking releases'}});
    node('updates-check').listeners.click(); await flush();
    const check = {request: calls.at(-1), busy: node('updates-progress').hidden === false,
        disabled: node('update-rtk-install').disabled};
    responses.push({data: idle}); await timers[0](); await flush();
    responses.push({data: {...idle, busy: true, stage: 'installing', message: 'Installing RTK'}});
    node('update-rtk-install').listeners.click(); await flush();
    const install = calls.at(-1);
    node('library-updates').open = false;
    const beforeBusyClosed = calls.length;
    responses.push({data: {...idle, components: idle.components.map(c => ({...c, restart_required:c.id==='headroom'}))}});
    await timers[0](); await flush();
    const busyClosedPolls = calls.length - beforeBusyClosed;
    node('library-updates').open = true;
    const restart = node('updates-restart').textContent;
    responses.push({ok:false,data:{error:'Another update is running'}});
    node('update-headroom-rollback').listeners.click(); await flush();
    const failedRequest = calls.at(-1);
    const failure = node('updates-error').textContent;
    responses.push({data: idle}); await timers[0](); await flush();
    const afterError = calls.at(-1);
    node('library-updates').open = false;
    const beforeClosed = calls.length; await timers[0](); await flush();
    process.stdout.write(JSON.stringify({startupCalls, opened, check, install, restart, failure,
        failedRequest, afterError, busyClosedPolls, closedPolls:calls.length-beforeClosed}));
})().catch(error => {process.stderr.write(error.stack); process.exitCode=1;});
'''
    result = subprocess.run(['node', '-e', harness], input=json.dumps(script), text=True,
                            capture_output=True, check=True, timeout=10)
    data = json.loads(result.stdout)
    assert data['startupCalls'] == 0
    assert data['opened'] == {'calls': 1, 'current': '0.37.0', 'latest': '0.37.0', 'canUpdate': True,
                              'updateLabel': 'Refresh dependencies',
                              'log': 'Operation log: updates/last-operation.log inside your Codex Token Saver folder.'}
    assert json.loads(data['check']['request']['body']) == {'action': 'check'}
    assert data['check']['request']['headers']['X-Codex-Update-Token'] == 'csrf-fixture'
    assert data['check']['busy'] and data['check']['disabled']
    assert json.loads(data['install']['body']) == {'action': 'install', 'component': 'rtk'}
    assert 'Restart Codex to update any file tools already running' in data['restart']
    assert 'Another update is running' in data['failure']
    assert json.loads(data['failedRequest']['body']) == {'action': 'rollback', 'component': 'headroom'}
    assert data['afterError'].get('method', 'GET') == 'GET'
    assert data['busyClosedPolls'] == 1
    assert data['closedPolls'] == 0
