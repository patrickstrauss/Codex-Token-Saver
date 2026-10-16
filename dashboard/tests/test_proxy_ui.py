"""Exercise the shipped controller; no network requests or production configuration."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Requires Node for shipped JavaScript')
def test_proxy_states_actions_recovery_and_no_retry():
    script_path = Path(__file__).parents[1] / 'static' / 'proxy.js'
    assert script_path.exists(), 'Desktop request proxy UI is missing'
    script = script_path.read_text(encoding='utf-8')
    harness = r'''
const vm = require('node:vm');
const source = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const nodes = {}, calls = [], responses = [], timers = [];
function node(id) { return nodes[id] ||= {textContent:'',hidden:false,disabled:false,listeners:{},
 addEventListener(t, fn) { this.listeners[t]=fn; }}; }
const paused = {installed:true,validated:true,enabled:false,route_enabled:false,ready:true,backend_ready:true,
 mode:'paused',restart_required:false,requests:{optimized:2,direct:1,failed:0,active:0},
 savings:{available:true,saved_tokens:4321,estimated:true,requests:2,last_recorded_at:'2026-09-13T12:00:00Z'}};
responses.push({data:paused});
const context = {document:{getElementById:node,querySelector:()=>({content:'csrf-fixture'}),hidden:false},
 setInterval(fn, delay) {timers.push({fn,delay});},fetch:async(url,opts={})=>{
 calls.push({url,...opts});const reply=responses.shift();if(!reply) throw new Error('No response');
 return {ok:reply.ok!==false,json:async()=>reply.data};}};
vm.createContext(context);vm.runInContext(source,context);
async function flush(){for(let i=0;i<10;i++)await Promise.resolve();}
function view(){return {status:node('request-proxy-status').textContent,saved:node('request-proxy-saved').textContent,
 enable:!node('request-proxy-enable').disabled,pause:!node('request-proxy-pause').disabled,
 restart:!node('request-proxy-restart').hidden,error:node('request-proxy-error').textContent};}
(async()=>{
 await flush();const initial=view();
 responses.push({data:{...paused,enabled:true,route_enabled:false}});
 await timers[0].fn();await flush();const prepared=view();
 responses.push({data:{...paused,enabled:true,route_enabled:true,mode:'optimized',restart_required:true}});
 node('request-proxy-enable').listeners.click();await flush();const enabled=view(),enableRequest=calls.at(-1);
 responses.push({data:{...paused,enabled:true,route_enabled:true,mode:'direct',backend_ready:false}});
 await timers[0].fn();await flush();const direct=view();
 responses.push({ok:false,data:{error:'Pause failed. Check the current state.'}});
 node('request-proxy-pause').listeners.click();await flush();const error=view(),pauseRequest=calls.at(-1);
 responses.push({data:{...paused,ready:false,backend_ready:false,mode:'offline',savings:{available:false}}});
 await timers[0].fn();await flush();const recovered=view(),last=calls.at(-1);
 context.document.hidden=true;const beforeHidden=calls.length;await timers[0].fn();await flush();
 process.stdout.write(JSON.stringify({initial,prepared,enabled,direct,error,recovered,enableRequest,pauseRequest,last,
  interval:timers[0].delay,hiddenPolls:calls.length-beforeHidden}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1;});
'''
    result = subprocess.run(['node', '-e', harness], input=json.dumps(script), text=True,
                            capture_output=True, check=True, timeout=10)
    data = json.loads(result.stdout)
    assert data['initial']['enable'] and not data['initial']['pause']
    assert data['initial']['saved'] == 'Unavailable'  # No recent ledger supplied.
    assert not data['initial']['restart']
    assert data['prepared']['enable'] and data['prepared']['pause']
    assert data['enabled']['pause'] and not data['enabled']['enable']
    assert data['enabled']['restart']
    assert 'optimized' in data['enabled']['status'].lower()
    assert 'direct' in data['direct']['status'].lower()
    assert json.loads(data['enableRequest']['body']) == {'action': 'enable'}
    assert data['enableRequest']['headers']['X-Codex-Update-Token'] == 'csrf-fixture'
    assert json.loads(data['pauseRequest']['body']) == {'action': 'pause'}
    assert 'Pause failed' in data['error']['error']
    assert data['last'].get('method', 'GET') == 'GET'
    assert data['recovered']['error'] == ''
    assert data['recovered']['saved'] == 'Unavailable'
    assert data['interval'] == 5000 and data['hiddenPolls'] == 0


@pytest.mark.skipif(shutil.which('node') is None, reason='Requires Node for shipped JavaScript')
def test_rolling_day_refreshes_without_substituting_lifetime():
    script = (Path(__file__).parents[1] / 'static' / 'proxy.js').read_text(encoding='utf-8')
    harness = r'''
const vm=require('node:vm'), source=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const nodes={}, calls=[], responses=[], timers=[];
function node(id){return nodes[id]||=( {textContent:'',hidden:false,disabled:false,value:'',listeners:{},
 addEventListener(t,fn){this.listeners[t]=fn;}});}
const recent={available:true,complete:true,windows:{
 last_24_hours:{saved_tokens:123,requests:4,reduction_pct:12.3}}};
const state={mode:'optimized',savings:{available:true,saved_tokens:99999,requests:1000},recent_savings:recent};
responses.push(state);
const context={document:{getElementById:node,querySelector:()=>({content:'fixture'}),hidden:false},
 setInterval(fn){timers.push(fn);},fetch:async(url,options={})=>{calls.push({url,...options});
 return {ok:true,json:async()=>responses.shift()};}};
vm.createContext(context);vm.runInContext(source,context);
async function flush(){for(let i=0;i<10;i++)await Promise.resolve();}
function view(){return {saved:node('request-proxy-saved').textContent,scope:node('request-proxy-scope').textContent,
 detail:node('request-proxy-window-detail').textContent,coverage:node('request-proxy-coverage').textContent};}
(async()=>{
 await flush();const initial=view();
 responses.push({...state,recent_savings:{...recent,windows:{last_24_hours:{saved_tokens:150,requests:5}}}});
 await timers[0]();await flush();const refreshed=view();
 responses.push({...state,recent_savings:{...recent,complete:false,truncated:true}});
 await timers[0]();await flush();const partial=view();
 responses.push({...state,recent_savings:{...recent,available:false,complete:false}});
 await timers[0]();await flush();const unavailable=view();
 responses.push({mode:'optimized',savings:state.savings});
 await timers[0]();await flush();const missing=view();
 responses.push({...state,recent_savings:{...recent,windows:{today:{saved_tokens:9999}}}});
 await timers[0]();await flush();const missingWindow=view();
 process.stdout.write(JSON.stringify({initial,refreshed,partial,unavailable,missing,missingWindow,calls}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1;});
'''
    result = subprocess.run(['node', '-e', harness], input=json.dumps(script), text=True,
                            capture_output=True, check=True, timeout=10)
    data = json.loads(result.stdout)
    assert data['initial']['saved'] == '123'
    assert 'last 24 hours' in data['initial']['scope']
    assert 'all tasks' in data['initial']['scope']
    assert '4 savings events' in data['initial']['detail']
    assert '12.3%' in data['initial']['detail']
    assert 'within recorded events' in data['initial']['detail']
    assert 'zero-savings requests and expansions are excluded' in data['initial']['coverage']
    assert 'not an overall traffic reduction rate' in data['initial']['coverage']
    assert data['refreshed']['saved'] == '150'
    assert all(call.get('method', 'GET') == 'GET' for call in data['calls'])
    assert data['partial']['saved'] == '123'
    assert 'Partial ledger coverage' in data['partial']['coverage']
    assert 'Partial record coverage' in data['partial']['scope']
    for key in ('unavailable', 'missing', 'missingWindow'):
        assert data[key]['saved'] == 'Unavailable'
        assert 'last 24 hours' in data[key]['scope']
        assert 'No readable records' in data[key]['detail']


@pytest.mark.skipif(shutil.which('node') is None, reason='Requires Node for shipped JavaScript')
def test_backend_rates_have_separate_scope_and_hide_missing_measurements():
    script = (Path(__file__).parents[1] / 'static' / 'proxy.js').read_text(encoding='utf-8')
    harness = r'''
const vm=require('node:vm'), source=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const nodes={}, responses=[], timers=[], calls=[];
function node(id){return nodes[id]||={textContent:'',hidden:false,disabled:false,value:'',listeners:{},
 addEventListener(t,fn){this.listeners[t]=fn;}};}
const metrics={scope:'backend_counters',collected_at:'2026-09-21T03:00:00Z',
 active_reduction_pct:58.8,whole_reduction_pct:1.8,
 diagnostics:{frames_attempted:300,frames_compressed:90,frames_failed:5,
 compression_average_ms:123.4,compression_max_ms:5001,compression_samples:300}};
const state={mode:'optimized',backend_metrics:metrics,savings:{available:true,saved_tokens:9999,requests:600}};
responses.push(state);
const context={document:{getElementById:node,querySelector:()=>({content:'fixture'}),hidden:false},
 setInterval(fn){timers.push(fn);},fetch:async(url,options={})=>{calls.push({url,...options});
 return {ok:true,json:async()=>responses.shift()};}};
vm.createContext(context);vm.runInContext(source,context);
async function flush(){for(let i=0;i<10;i++)await Promise.resolve();}
function view(){return {saved:node('request-proxy-saved').textContent,active:node('request-proxy-active-rate').textContent,
 whole:node('request-proxy-whole-rate').textContent,scope:node('request-proxy-backend-scope').textContent,
 diagnostics:node('request-proxy-diagnostics').textContent,timing:node('request-proxy-timing').textContent,
 status:node('request-proxy-status').textContent,savingsScope:node('request-proxy-scope').textContent,
 counts:node('request-proxy-counts').textContent,timingHidden:node('request-proxy-timing').hidden};}
(async()=>{
 await flush();const initial=view(),before=calls.length;
 responses.push({...state,backend_metrics:{...metrics,active_reduction_pct:null,whole_reduction_pct:null,diagnostics:{}}});
 await timers[0]();await flush();const unavailable=view();
 responses.push({...state,backend_metrics:undefined});await timers[0]();await flush();const missing=view();
 responses.push({...state,backend_metrics:{...metrics,active_reduction_pct:0,whole_reduction_pct:0,
 diagnostics:{frames_attempted:0,frames_compressed:0,frames_failed:0}}});
 await timers[0]();await flush();const zero=view();
 responses.push({...state,mode:'opencodex',enabled:true,effective_enabled:true,savings_history_only:false,
 savings:{available:true,saved_tokens:750,requests:2,reduction_pct:75},
 recent_savings:{available:true,complete:true,windows:{last_24_hours:{saved_tokens:750,requests:2,reduction_pct:75}}},
 transform_outcomes:{compressed:3,unchanged:2,bypassed:1,error:0}});
 await timers[0]();await flush();const opencodex=view();
 responses.push(state);await timers[0]();await flush();const restored=view();
 process.stdout.write(JSON.stringify({initial,unavailable,missing,zero,opencodex,restored,extraCalls:calls.length-before}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1;});
'''
    result = subprocess.run(['node', '-e', harness], input=json.dumps(script), text=True,
                            capture_output=True, check=True, timeout=10)
    data = json.loads(result.stdout)
    assert data['initial']['active'] == '58.8%'
    assert data['initial']['whole'] == '1.8%'
    assert 'backend counters' in data['initial']['scope']
    assert '24-hour savings total' in data['initial']['scope']
    assert '300 attempted' in data['initial']['diagnostics']
    assert '5 failed' in data['initial']['diagnostics']
    assert 'timeout' not in data['initial']['diagnostics'].lower()
    assert '123.4 ms average' in data['initial']['timing']
    assert '300 measured' in data['initial']['timing']
    for key in ('unavailable', 'missing'):
        assert data[key]['active'] == data[key]['whole'] == 'Unavailable'
        assert 'Unavailable' in data[key]['diagnostics']
        assert 'Unavailable' in data[key]['timing']
    assert data['zero']['active'] == data['zero']['whole'] == '0%'
    assert '0 attempted' in data['zero']['diagnostics']
    assert data['opencodex']['saved'] == '750'
    assert data['opencodex']['active'] == '75%'
    assert data['opencodex']['whole'] == 'Not reported'
    assert 'enabled' in data['opencodex']['status']
    assert 'OpenCodex tool results' in data['opencodex']['savingsScope']
    assert 'last 24 hours' in data['opencodex']['scope']
    assert '3 compressed' in data['opencodex']['counts']
    assert data['opencodex']['timingHidden']
    assert data['restored'] == data['initial']
    assert data['extraCalls'] == 5  # Polls never change routing.
