"""Task links exercise the shipped JavaScript, including delayed and wrong-task replies."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Requires Node for shipped JavaScript')
def test_task_link_lookup_is_local_explicit_and_race_safe():
    source = (Path(__file__).parents[1] / 'static/components.js').read_text(encoding='utf-8')
    harness = r'''
const vm=require('node:vm'), assert=require('node:assert/strict');
const nodes={},calls=[],pending=[],timers=[];let count=0,delayLookup=false,delaySummary=false,wrongTask=false,job=null;
const older='01a09946-380f-72f1-ab4a-29bb5da7b861',recent='a6e593dc-4bd7-40f6-8250-ae9d8990efe4',missing='a6e593dc-4bd7-40f6-8250-ae9d8990efe5';
function node(id){return nodes[id] ||= {children:[],dataset:{},listeners:{},value:'',checked:false,disabled:false,textContent:'',hidden:false,
 setAttribute(k,v){this[k]=v},append(...items){this.children.push(...items);items.forEach(x=>{if(x.id)nodes[x.id]=x})},
 replaceChildren(...items){this.children=items},addEventListener(k,v){this.listeners[k]=v},focus(){this.focused=true}}}
const reply=(data,ok=true)=>({ok,json:async()=>data});
const context={document:{getElementById:node,querySelector:()=>({content:'csrf'}),createElement:()=>node('new-'+count++),hidden:false},
 Option:function(text,value){return{textContent:text,value}},setInterval(fn){timers.push(fn)},
 fetch:async(url,options={})=>{calls.push({url,...options});
 if(url==='/api/components')return reply({components:['local_summaries','llama_cpp'].map(id=>({id,effective_enabled:true,available:true,state:'ready'}))});
 if(url==='/api/summary-reminders')return reply({enabled:false,threshold_percent:70,tasks:[]});
 if(url.includes('/lookup?')){const ref=decodeURIComponent(url.split('=')[1]),id=ref.replace('codex://threads/','').trim().toLowerCase();
  const result=id===missing?reply({error:'This task was not found on this device.'},false):reply({task:{task_id:wrongTask?recent:id,title:'<script>'+id+'</script>',updated_at:'2026-09-20T07:00:00Z'}});
  if(delayLookup)return new Promise(resolve=>pending.push({id,resolve:()=>resolve(result)}));return result;}
 if(url.includes('?task_id=')){const id=url.split('=')[1],result=reply({task_id:id,summary:'Summary for '+id,status:'partial',coverage:{summarized_messages:2,total_messages:4,pending_messages:2}});
  if(delaySummary)return new Promise(resolve=>pending.push({id,resolve:()=>resolve(result)}));return result;}
 if(options.method==='POST')return reply({status:'running'});
 return reply({status:{available:true,running:false,job},tasks:[{task_id:recent,title:'Recent task'}]});}};
vm.createContext(context);vm.runInContext(JSON.parse(require('node:fs').readFileSync(0,'utf8')),context);
async function flush(){for(let i=0;i<40;i++)await Promise.resolve()}
async function lookup(value){node('local-summary-link').value=value;node('local-summary-link').listeners.input();node('local-summary-lookup-form').listeners.submit({preventDefault(){}});await flush()}
function noPosts(){assert.equal(calls.filter(c=>c.method==='POST').length,0)}
(async()=>{
 await flush();node('local-summary-panel').open=true;node('local-summary-panel').listeners.toggle();await flush();
 const before=calls.length;
 for(const value of ['', '../private','https://example.com','codex://threads/'+older+'?view=review','codex://threads/'+older+'#extra','codex://threads/'+older+'/extra']) {
  await lookup(value);assert.match(node('local-summary-lookup-error').textContent,/Paste a Codex task link/);assert(node('local-summary-refresh').disabled);}
 assert.equal(calls.length,before);noPosts();
 await lookup('codex://threads/'+older);assert.equal(node('local-summary-task').value,older);assert.equal(node('local-summary-title').textContent,'<script>'+older+'</script>');
 assert(!node('local-summary-refresh').disabled);assert.match(node('local-summary-quality').textContent,/Not ready for a handoff/);noPosts();
 timers[0]();await flush();assert.equal(node('local-summary-task').value,older);assert(node('local-summary-task').children.some(x=>x.value===older));
 await lookup(missing);assert.match(node('local-summary-lookup-error').textContent,/not found on this device/);assert(node('local-summary-selection').hidden);assert(node('local-summary-refresh').disabled);assert(!node('local-summary-text').textContent.includes(older));
 wrongTask=true;await lookup(older);assert.match(node('local-summary-lookup-error').textContent,/different task/);assert(node('local-summary-refresh').disabled);wrongTask=false;
 delayLookup=true;await lookup(older);await lookup(recent);pending.find(x=>x.id===recent).resolve();await flush();pending.find(x=>x.id===older).resolve();await flush();
 assert.equal(node('local-summary-task').value,recent);assert.equal(node('local-summary-text').textContent,'Summary for '+recent);pending.length=0;delayLookup=false;
 delaySummary=true;await lookup(older);delaySummary=false;await lookup(recent);pending[0].resolve();await flush();
 assert.equal(node('local-summary-task').value,recent);assert.equal(node('local-summary-text').textContent,'Summary for '+recent);pending.length=0;
 delayLookup=true;await lookup(older);node('local-summary-link').value='editing';node('local-summary-link').listeners.input();pending[0].resolve();await flush();
 assert(node('local-summary-selection').hidden);assert(node('local-summary-refresh').disabled);assert.equal(node('local-summary-task').value,'');pending.length=0;delayLookup=false;
 job={task_id:older,error:'The local model timed out. Completed batches are saved.',error_code:'model_timeout',error_stage:'summarizing'};
 await lookup(older);timers[0]();await flush();assert.match(node('local-summary-error').textContent,/timed out/);assert.match(node('local-summary-diagnostic').textContent,/model_timeout/);
 await lookup(recent);assert.equal(node('local-summary-error').textContent,'');assert.equal(node('local-summary-diagnostic').textContent,'');noPosts();
 node('local-summary-refresh').listeners.click();await flush();
 const posts=calls.filter(c=>c.method==='POST');assert.equal(posts.length,1);assert.deepEqual(JSON.parse(posts[0].body),{action:'start',task_id:recent});
 assert.equal(posts[0].headers['X-Codex-Update-Token'],'csrf');
 process.stdout.write('Task lookup: invalid, missing, older, wrong-task, delayed lookup/read, edited input, error details, explicit start passed.');
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1});
'''
    result = subprocess.run(['node', '-e', harness], input=json.dumps(source), text=True,
                            encoding='utf-8', capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
