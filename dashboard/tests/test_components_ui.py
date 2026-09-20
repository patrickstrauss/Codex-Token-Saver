"""Run the shipped script against a deterministic DOM and network boundary."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Requires Node for shipped JavaScript')
@pytest.mark.parametrize('summary_status,coverage_extra,expected_quality', [
    ('summarized', {}, 'all currently readable segments'),
    ('partial', {'source_incomplete': True}, 'unfinished transcript record'),
    ('partial', {'incomplete_tool_pairs': 2}, '2 tool calls have no matching result'),
    ('partial', {'source_truncated': True, 'skipped_lines': 3}, '3 source records were skipped'),
    ('stale', {}, 'Stale summary'),
])
def test_toggles_are_independent_and_summary_inference_requires_a_click(summary_status, coverage_extra, expected_quality):
    source = (Path(__file__).parents[1] / 'static/components.js').read_text(encoding='utf-8')
    harness = r'''
const vm = require('node:vm');
const fixture = JSON.parse(require('node:fs').readFileSync(0, 'utf8')), source = fixture.source;
const nodes = {}, calls = [], timers = [];
function node(id) { return nodes[id] ||= {children:[],dataset:{},listeners:{},value:'',checked:false,disabled:false,textContent:'',
 setAttribute(k,v){this[k]=v},append(...n){this.children.push(...n);n.forEach(x=>{if(x.id)nodes[x.id]=x;})},
 replaceChildren(...n){this.children=n},addEventListener(k,v){this.listeners[k]=v}}; }
const names=['rtk','headroom_local','headroom_requests','serena','local_summaries','llama_cpp'];
let state={overall_health:'ok',selected_count:4,components:names.map(id=>({id,available:id!=='serena',requested_enabled:!['serena','headroom_requests'].includes(id),effective_enabled:!['serena','headroom_requests'].includes(id),state:id==='serena'?'off':'ready'}))};
const task='a6e593dc-4bd7-40f6-8250-ae9d8990efe4';let n=0,started=false;
const context={document:{getElementById:node,querySelector:()=>({content:'csrf'}),createElement:()=>node('created-'+n++),hidden:false},
 Option:function(text,value){return{textContent:text,value}},setInterval(fn){timers.push(fn)},
 fetch:async(url,options={})=>{calls.push({url,...options});let data;
 if(url==='/api/components'){if(options.method==='POST'){const b=JSON.parse(options.body);state={...state,components:state.components.map(c=>c.id===b.component?{...c,requested_enabled:b.enabled,effective_enabled:b.enabled,state:b.enabled?'ready':'off'}:c)}}data={...state,...(options.method==='POST'?{change:{restart_required:true}}:{})};}
 else if(url.includes('/lookup?'))data={task:{task_id:task,title:'Fixture task'}};
 else if(url.includes('?task_id='))data={task_id:task,status:fixture.status,summary:'<script>is displayed as text</script>',coverage:{summarized_messages:4,total_messages:4,pending_messages:0,...fixture.coverage}};
 else {if(options.method==='POST' && url==='/api/local-summaries')started=true;
 data={status:{available:true,running:started,job:started?{task_id:task,phase:'summarizing',processed_messages:6,total_messages:14,batches_completed:1}:null},tasks:[{task_id:task,project:'fixture'}]};}
 return{ok:true,json:async()=>data};}};
vm.createContext(context);vm.runInContext(source,context);
async function flush(){for(let i=0;i<20;i++)await Promise.resolve()}
(async()=>{await flush();const initialCalls=calls.slice(),unavailable=node('component-serena').disabled;
 node('component-rtk').checked=false;node('component-rtk').listeners.change();await flush();
 const change=calls.at(-1),localStillOn=node('component-headroom_local').checked,reloadNotice=node('components-notice').textContent;
 node('local-summary-panel').open=true;await node('local-summary-panel').listeners.toggle();await flush();
 node('local-summary-task').value=task;node('local-summary-task').listeners.change.call(node('local-summary-task'));await flush();
 const ready=!node('local-summary-refresh').disabled,priorPosts=calls.filter(x=>x.method==='POST').length;
 node('local-summary-refresh').listeners.click();await flush();
 const posted=calls.filter(x=>x.method==='POST').at(-1),summary=node('local-summary-text').textContent;
 context.document.hidden=true;const before=calls.length;timers[0]();await flush();
 process.stdout.write(JSON.stringify({initialCalls,unavailable,change,localStillOn,reloadNotice,ready,priorPosts,posted,summary,quality:node('local-summary-quality').textContent,progress:node('local-summary-status').textContent,hiddenPolls:calls.length-before}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1});
'''
    result = subprocess.run(['node', '-e', harness], input=json.dumps({'source': source, 'status': summary_status, 'coverage': coverage_extra}), text=True,
                            capture_output=True, check=True, timeout=10)
    data = json.loads(result.stdout)
    assert len(data['initialCalls']) == 1 and data['initialCalls'][0]['url'] == '/api/components'
    assert data['unavailable'] and data['localStillOn']
    assert json.loads(data['change']['body']) == {'component': 'rtk', 'enabled': False}
    assert data['change']['headers']['X-Codex-Update-Token'] == 'csrf'
    assert 'configuration changed. Reload Codex' in data['reloadNotice']
    assert data['ready'] and data['priorPosts'] == 1
    assert json.loads(data['posted']['body']) == {'action': 'start', 'task_id': 'a6e593dc-4bd7-40f6-8250-ae9d8990efe4'}
    assert data['summary'] == '<script>is displayed as text</script>'
    assert data['hiddenPolls'] == 0
    assert expected_quality in data['quality']
    assert '6 of 14 segments; 1 batches completed' in data['progress']
    if summary_status != 'summarized':
        assert 'all currently readable segments' not in data['quality']


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
