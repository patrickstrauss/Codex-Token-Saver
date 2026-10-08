"""Run the shipped script against a deterministic DOM and network boundary."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Requires Node for shipped JavaScript')
def test_toggles_are_independent_and_retired_panels_are_absent():
    source = (Path(__file__).parents[1] / 'static/components.js').read_text(encoding='utf-8')
    harness = r'''
const vm = require('node:vm');
const fixture = JSON.parse(require('node:fs').readFileSync(0, 'utf8')), source = fixture.source;
const nodes = {}, calls = [], timers = [];
function node(id) { return nodes[id] ||= {children:[],dataset:{},listeners:{},value:'',checked:false,disabled:false,textContent:'',
 setAttribute(k,v){this[k]=v},append(...n){this.children.push(...n);n.forEach(x=>{if(x.id)nodes[x.id]=x;})},
 replaceChildren(...n){this.children=n},addEventListener(k,v){this.listeners[k]=v}}; }
const names=['rtk','headroom_local','headroom_requests','serena','playwright_cli','ast_grep','laya_router'];
let state={overall_health:'ok',selected_count:4,components:names.map(id=>({id,available:id!=='serena',requested_enabled:!['serena','headroom_requests'].includes(id),effective_enabled:!['serena','headroom_requests'].includes(id),state:id==='serena'?'off':'ready'}))};
let n=0;
const context={document:{getElementById:node,querySelector:()=>({content:'csrf'}),createElement:()=>node('created-'+n++),hidden:false},
 Option:function(text,value){return{textContent:text,value}},setInterval(fn){timers.push(fn)},
 fetch:async(url,options={})=>{calls.push({url,...options});let data;
 if(url==='/api/components'){if(options.method==='POST'){const b=JSON.parse(options.body);state={...state,components:state.components.map(c=>c.id===b.component?{...c,requested_enabled:b.enabled,effective_enabled:b.enabled,state:b.enabled?'ready':'off'}:c)}}data={...state,...(options.method==='POST'?{change:{restart_required:true}}:{})};}
 else if(url==='/api/bundle/disable')data={opened:true};
 else throw new Error('Unexpected API: '+url);
 return{ok:true,json:async()=>data};}};
vm.createContext(context);vm.runInContext(source,context);
async function flush(){for(let i=0;i<20;i++)await Promise.resolve()}
(async()=>{await flush();const initialCalls=calls.slice(),unavailable=node('component-serena').disabled;
 node('component-rtk').checked=false;node('component-rtk').listeners.change();await flush();
 const change=calls.at(-1),localStillOn=node('component-headroom_local').checked,reloadNotice=node('components-notice').textContent;
 const beforeDisable=calls.length,disableClick=node('bundle-disable').listeners.click;
 const opening=disableClick.call(node('bundle-disable'));disableClick.call(node('bundle-disable'));await opening;await flush();
 const disable={calls:calls.length-beforeDisable,request:calls.at(-1),message:node('bundle-disable-status').textContent,enabled:!node('bundle-disable').disabled};
 context.document.hidden=true;const before=calls.length;timers[0]();await flush();
 process.stdout.write(JSON.stringify({initialCalls,unavailable,change,localStillOn,reloadNotice,disable,retiredPanels:Object.keys(nodes).filter(id=>id.includes('summary')||id.includes('llama')), hiddenPolls:calls.length-before}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1});
'''
    result = subprocess.run(['node', '-e', harness], input=json.dumps({'source': source}), text=True,
                            capture_output=True, check=True, timeout=10)
    data = json.loads(result.stdout)
    assert len(data['initialCalls']) == 1 and data['initialCalls'][0]['url'] == '/api/components'
    assert data['unavailable'] and data['localStillOn']
    assert json.loads(data['change']['body']) == {'component': 'rtk', 'enabled': False}
    assert data['change']['headers']['X-Codex-Update-Token'] == 'csrf'
    assert 'configuration changed. Reload Codex' in data['reloadNotice']
    assert data['retiredPanels'] == []
    assert data['hiddenPolls'] == 0
    assert data['disable']['calls'] == 1 and data['disable']['enabled']
    assert data['disable']['request']['url'] == '/api/bundle/disable'
    assert data['disable']['request']['headers']['X-Codex-Update-Token'] == 'csrf'
    assert json.loads(data['disable']['request']['body']) == {'action': 'open'}
    assert 'Nothing is disabled until you confirm' in data['disable']['message']


def test_selected_component_failure_reaches_dashboard_health(monkeypatch):
    import app
    monkeypatch.setattr(app, 'collect_components', lambda observations: {'components': [], 'overall_health': 'error'})
    monkeypatch.setattr(app, 'collect_rtk', lambda: {'active': False, 'records_readable': True, 'total_saved': 10, 'history': []})
    monkeypatch.setattr(app, 'collect_headroom', lambda: None)
    monkeypatch.setattr(app, 'collect_desktop_headroom', lambda: {})
    snapshot = app.collect_all()
    assert snapshot['rtk']['health'] == 'ok'
    assert snapshot['rtk']['active'] is False
    assert snapshot['overall_health'] == 'error'


@pytest.mark.skipif(shutil.which('node') is None, reason='Requires Node for shipped JavaScript')
def test_serena_diagnostics_render_as_historical_text_and_clear_after_refresh():
    source = (Path(__file__).parents[1] / 'static/components.js').read_text(encoding='utf-8')
    harness = r'''
const vm = require('node:vm'), nodes = {}, timers = [];
const source = JSON.parse(require('node:fs').readFileSync(0, 'utf8')).source;
function node(id) { return nodes[id] ||= {children:[],dataset:{},listeners:{},textContent:'',
 set innerHTML(value){throw new Error('Diagnostics must be text')},
 setAttribute(k,v){this[k]=v}, append(...children){this.children.push(...children);children.forEach(x=>{x.parent=this;if(x.id)nodes[x.id]=x;})},
 addEventListener(k,v){this.listeners[k]=v}}; }
let count=0, diagnostics={last_elapsed_ms:0,last_tool:'find_symbol',
 last_failure:'<img src=x onerror=alert(1)> historical missing path',last_failure_at:'2026-09-20T14:22:40Z'};
const context={document:{getElementById:node,querySelector:()=>({content:'csrf'}),createElement:()=>node('node-'+count++),hidden:false},
 setInterval(fn){timers.push(fn)},fetch:async()=>({ok:true,json:async()=>({overall_health:'ok',selected_count:1,
 components:[{id:'serena',available:true,requested_enabled:true,state:'configured',last_error:null,diagnostics}]})})};
vm.createContext(context);vm.runInContext(source,context);
async function flush(){for(let i=0;i<20;i++)await Promise.resolve()}
(async()=>{await flush();const box=node('component-serena').parent.parent.parent;
 const diagnostic=box.children[4],problem=box.children[5];
 const first={text:diagnostic.textContent,hidden:diagnostic.hidden,problem:problem.textContent};
 diagnostics={};timers[0]();await flush();
 process.stdout.write(JSON.stringify({first,next:{text:diagnostic.textContent,hidden:diagnostic.hidden}}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1});
'''
    result = subprocess.run(['node', '-e', harness], input=json.dumps({'source': source}), text=True,
                            capture_output=True, check=True, timeout=10)
    data = json.loads(result.stdout)
    assert data['first']['hidden'] is False
    assert 'Last tool duration: 0 ms (find_symbol)' in data['first']['text']
    assert 'Last recorded failure: <img src=x onerror=alert(1)> historical missing path' in data['first']['text']
    assert 'Not recorded' not in data['first']['text']
    assert data['first']['problem'] == ''
    assert data['next'] == {'text': '', 'hidden': True}
