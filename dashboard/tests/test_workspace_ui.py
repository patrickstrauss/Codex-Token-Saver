"""Navigation stays read-only and usable when appearance storage is blocked."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Requires Node for shipped JavaScript')
@pytest.mark.parametrize('storage_blocked', [False, True])
def test_workspace_navigation_appearance_and_connection_state(storage_blocked):
    script = (Path(__file__).parents[1] / 'static/dashboard.js').read_text(encoding='utf-8')
    harness = r'''
const vm = require('node:vm');
const fixture = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const handlers = {}, nodes = {}, stored = [], keys = ['overview','toolkit','activity','updates','diagnostics'];
function node(id) { return nodes[id] ||= {dataset:{},attributes:{},textContent:'',hidden:false,
 parentElement:{dataset:{}},classList:{contains(k){return (this.value||'').split(' ').includes(k)}},
 setAttribute(k,v){this.attributes[k]=v},removeAttribute(k){delete this.attributes[k]},
 addEventListener(k,v){this[k]=v},focus(){this.focused=true}}; }
const views=keys.map(k=>Object.assign(node('view-'+k),{dataset:{workspaceView:k}}));
const links=keys.map(k=>Object.assign(node('link-'+k),{dataset:{viewLink:k}}));
let observer;
const context={document:{documentElement:{dataset:{}},title:'',getElementById:node,
 querySelectorAll:q=>q==='[data-view-link]'?links:views}, location:{hash:'#not-a-view',reload(){context.reloaded=true}},
 window:{addEventListener(k,v){handlers[k]=v},scrollTo(){}},
 localStorage:{getItem(){if(fixture.blocked)throw new Error();return 'light'},setItem(k,v){if(fixture.blocked)throw new Error();stored.push([k,v])}},
 MutationObserver:function(callback){observer=callback;this.observe=()=>{}},
 fetch(){throw new Error('Workspace UI must not issue requests')}};
node('health-pulse').dataset.pending='true';
vm.createContext(context);vm.runInContext(fixture.source,context);
function current(){return views.filter(v=>!v.hidden).map(v=>v.dataset.workspaceView)}
const initial={views:current(),theme:context.document.documentElement.dataset.theme,connection:node('connection-label').textContent};
context.location.hash='#toolkit';handlers.hashchange();
const toolkit={views:current(),selected:node('link-toolkit').attributes['aria-current'],overviewSelected:node('link-overview').attributes['aria-current'],focused:node('page-title').focused};
context.location.hash='#updates';handlers.hashchange();
const updatesOpen=node('library-updates').open;
context.location.hash='#toolkit';handlers.hashchange();
const updatesClosed=!node('library-updates').open;
context.location.hash='#main-content';handlers.hashchange();
const skip=current();
node('theme-toggle').click();
const theme={value:context.document.documentElement.dataset.theme,label:node('theme-toggle').attributes['aria-label'],stored};
delete node('health-pulse').dataset.pending;observer();
const connected=node('connection-label').textContent;
node('health-pulse').classList.value='health-error';observer();
const failure=node('connection-label').textContent;
node('refresh-dashboard').click();
process.stdout.write(JSON.stringify({initial,toolkit,skip,theme,connected,failure,reloaded:context.reloaded,updatesOpen,updatesClosed}));
'''
    result = subprocess.run(['node', '-e', harness], input=json.dumps({'source': script, 'blocked': storage_blocked}),
                            capture_output=True, text=True, check=True, timeout=10)
    states = json.loads(result.stdout)
    assert states['initial']['views'] == ['overview']
    assert states['initial']['connection'] == 'Connecting'
    assert states['toolkit'] == {'views': ['toolkit'], 'selected': 'page', 'focused': True}
    assert states['skip'] == ['toolkit']
    assert states['theme']['value'] == ('light' if storage_blocked else 'dark')
    assert states['theme']['stored'] == ([] if storage_blocked else [['cts-theme', 'dark']])
    assert states['connected'] == 'Connected' and states['failure'] == 'Needs attention'
    assert states['reloaded']
    assert states['updatesOpen'] and states['updatesClosed']


@pytest.mark.skipif(shutil.which('node') is None, reason='Requires Node for shipped JavaScript')
def test_update_connection_recovers_without_erasing_interrupted_action():
    script = (Path(__file__).parents[1] / 'static/updates.js').read_text(encoding='utf-8')
    harness = r'''
const vm=require('node:vm'), source=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const nodes={},timers=[],calls=[];
function node(id){return nodes[id]||=( {textContent:'',hidden:false,disabled:false,listeners:{},addEventListener(k,fn){this.listeners[k]=fn}} )}
let fail=true;
const context={document:{getElementById:node,querySelector:()=>({content:'test'})},setInterval(fn){timers.push(fn)},
 fetch:async(url,options={})=>{calls.push(options.method||'GET');if(fail)throw new Error('Offline');return {ok:true,json:async()=>({components:[]})}}};
vm.createContext(context);vm.runInContext(source,context);
async function flush(){for(let i=0;i<20;i++)await Promise.resolve()}
(async()=>{
node('library-updates').open=true;node('library-updates').listeners.toggle();await flush();
const failed=node('updates-error').textContent;
fail=false;timers[0]();await flush();const recovered=node('updates-error').hidden;
fail=true;node('updates-check').listeners.click();await flush();const interrupted=node('updates-error').textContent;
fail=false;timers[0]();await flush();
process.stdout.write(JSON.stringify({failed,recovered,interrupted,preserved:node('updates-error').textContent,calls}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1});
'''
    result = subprocess.run(['node', '-e', harness], input=json.dumps(script),
                            capture_output=True, text=True, check=True, timeout=10)
    state = json.loads(result.stdout)
    assert 'status is unavailable' in state['failed'] and state['recovered']
    assert 'response was interrupted' in state['interrupted']
    assert state['preserved'] == state['interrupted']
    assert state['calls'] == ['GET', 'GET', 'POST', 'GET']
