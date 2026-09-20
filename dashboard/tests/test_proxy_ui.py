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
    assert data['initial']['saved'] == '4,321'
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
