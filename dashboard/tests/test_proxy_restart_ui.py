"""A historic config receipt is not proof that loaded tasks still need a restart."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Requires Node for shipped JavaScript')
def test_saved_restart_flag_is_advisory_and_new_changes_remain_visible():
    script = (Path(__file__).parents[1] / 'static/proxy.js').read_text(encoding='utf-8')
    harness = r'''
const vm=require('node:vm'),source=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
function setup(initial){
 const nodes={},timers=[],calls=[],responses=[initial];
 function node(id){return nodes[id]||={textContent:'',hidden:false,disabled:false,value:'today',listeners:{},addEventListener(k,fn){this.listeners[k]=fn}}}
 const context={document:{getElementById:node,querySelector:()=>({content:'test'}),hidden:false},setInterval(fn){timers.push(fn)},fetch:async(url,options={})=>{
  calls.push(options);return {ok:true,json:async()=>responses.shift()}}};
 vm.createContext(context);vm.runInContext(source,context);
 return {node,timers,calls,responses};
}
async function flush(){for(let i=0;i<20;i++)await Promise.resolve()}
function view(test){return {hidden:test.node('request-proxy-restart').hidden,text:test.node('request-proxy-restart').textContent,saved:test.node('request-proxy-saved').textContent,routing:test.node('request-proxy-routing').textContent}}
const running={mode:'optimized',installed:true,validated:true,enabled:true,route_enabled:true,ready:true,backend_ready:true,restart_required:true,
 recent_savings:{available:true,windows:{last_24_hours:{saved_tokens:100,requests:1}}}};
(async()=>{
 const test=setup(running);await flush();const initial=view(test);
 test.responses.push({...running,recent_savings:{available:true,windows:{last_24_hours:{saved_tokens:200,requests:2}}}});test.timers[0]();await flush();const ticking=view(test);
 const paused={...running,mode:'paused',enabled:false,route_enabled:false};
 test.responses.push(paused);test.node('request-proxy-pause').listeners.click();await flush();const changed=view(test);
 const reloaded=setup(paused);await flush();
 const ocx=setup({...running,mode:'opencodex'});await flush();
 process.stdout.write(JSON.stringify({initial,ticking,changed,reloaded:view(reloaded),ocx:view(ocx),methods:test.calls.map(c=>c.method||'GET')}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1});
'''
    result = subprocess.run(['node', '-e', harness], input=json.dumps(script),
                            capture_output=True, text=True, check=True, timeout=10)
    state = json.loads(result.stdout)
    assert state['initial']['hidden'] and state['ticking']['hidden']
    assert state['initial']['saved'] == '100' and state['ticking']['saved'] == '200'
    assert 'only if a task' in state['initial']['routing']
    assert not state['changed']['hidden'] and 'only if an already-open task' in state['changed']['text']
    assert state['reloaded']['hidden']
    assert not state['ocx']['hidden'] and 'OpenCodex must reload' in state['ocx']['text']
    assert state['methods'] == ['GET', 'GET', 'POST']
