"""Exercise the shipped reminder UI with metadata-only fixtures."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Requires Node for shipped JavaScript')
@pytest.mark.parametrize('active', [True, False])
@pytest.mark.parametrize('startup', ['', 'a6e593dc-4bd7-40f6-8250-ae9d8990efe4', '../private', None])
def test_reminder_selection_does_not_start_inference_and_save_is_explicit(active, startup):
    source = (Path(__file__).parents[1] / 'static/components.js').read_text(encoding='utf-8')
    harness = r'''
const vm=require('node:vm'), fixture=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const nodes={},calls=[],timers=[];let count=0;
function node(id){return nodes[id] ||= {children:[],dataset:{},listeners:{},value:'',checked:false,disabled:false,textContent:'',
 setAttribute(k,v){this[k]=v},append(...items){this.children.push(...items);items.forEach(x=>{if(x.id)nodes[x.id]=x})},
 replaceChildren(...items){this.children=items},addEventListener(k,v){this.listeners[k]=v},focus(){this.focused=true}}}
const task='a6e593dc-4bd7-40f6-8250-ae9d8990efe4', other='a6e593dc-4bd7-40f6-8250-ae9d8990efe5';
const names=['rtk','headroom_local','headroom_requests','serena','local_summaries','llama_cpp'];
let reminders={enabled:true,threshold_percent:70,active:fixture.active,reason:fixture.active?null:'Turn on LangMem and llama.cpp to receive reminders.',error:null,
 tasks:[{task_id:task,title:'<script>Literal task title</script>',input_tokens:210000,context_window:300000,context_percent:70,needs_summary:true},
        {task_id:other,title:'Missing latest context',input_tokens:null,context_window:null,context_percent:null,needs_summary:false}]};
const context={document:{getElementById:node,querySelector:()=>({content:'csrf-fixture'}),createElement:()=>node('new-'+count++),hidden:false},
 URLSearchParams,location:{search:fixture.startup?'?summary_task='+encodeURIComponent(fixture.startup):'',hash:fixture.startup===null?'#local-summary-panel':''},
 Option:function(text,value){return{textContent:text,value}},setInterval(fn){timers.push(fn)},
 fetch:async(url,options={})=>{calls.push({url,...options});let data;
 if(url==='/api/components')data={components:names.map(id=>({id,requested_enabled:true,effective_enabled:true,available:true,state:'ready'}))};
 else if(url==='/api/summary-reminders'){if(options.method==='POST'){const body=JSON.parse(options.body);reminders={...reminders,...body}}data=reminders}
 else if(url.includes('?task_id='))data={summary:'Saved summary',status:'summarized',coverage:{total_messages:2,summarized_messages:2}};
 else data={status:{available:true,running:false},tasks:[{task_id:task,project:'fixture'}]};
 return{ok:true,json:async()=>data}}};
vm.createContext(context);vm.runInContext(fixture.source,context);
async function flush(){for(let i=0;i<35;i++)await Promise.resolve()}
(async()=>{
 await flush();const initialCalls=calls.slice(),startupSelected=node('local-summary-task').value,startupOpen=!!node('local-summary-panel').open;node('local-summary-panel').open=true;
 node('local-summary-panel').listeners.toggle();await flush();
 const initialStatus=node('summary-reminder-status').textContent;
 const listed=node('summary-reminder-tasks').children.map(row=>({title:row.children[0].children[0].textContent,context:row.children[0].children[1].textContent}));
 if(fixture.active){await node('summary-reminder-tasks').children[0].children[1].listeners.click();await flush()}
 const selected=node('local-summary-task').value,focused=!!node('local-summary-task').focused;
 const inferenceReady=!node('local-summary-refresh').disabled,summary=node('local-summary-text').textContent;
 const postsBeforeSave=calls.filter(c=>c.method==='POST');
 node('summary-reminder-threshold').value='80';node('summary-reminder-threshold').listeners.input();
 timers[0]();await flush();const retained=node('summary-reminder-threshold').value;
 node('summary-reminder-threshold').value='19';node('summary-reminder-threshold').listeners.input();
 await node('summary-reminder-save').listeners.click();await flush();const invalidMessage=node('summary-reminder-error').textContent;
 const invalidPosts=calls.filter(c=>c.method==='POST').length;
 node('summary-reminder-threshold').value='80';node('summary-reminder-threshold').listeners.input();
 node('summary-reminder-enabled').checked=false;node('summary-reminder-enabled').listeners.change();
 await node('summary-reminder-save').listeners.click();await flush();
 const posts=calls.filter(c=>c.method==='POST'),saved=node('summary-reminder-save').disabled;
 context.document.hidden=true;const before=calls.length;timers[0]();await flush();
 process.stdout.write(JSON.stringify({initialCalls,startupSelected,startupOpen,initialStatus,listed,selected,focused,inferenceReady,summary,postsBeforeSave,retained,invalidMessage,invalidPosts,posts,saved,hiddenPolls:calls.length-before}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1});
'''
    result = subprocess.run(['node', '-e', harness], input=json.dumps({'source': source, 'active': active, 'startup': startup}),
                            text=True, encoding='utf-8', capture_output=True, check=True, timeout=10)
    data = json.loads(result.stdout)
    if startup == 'a6e593dc-4bd7-40f6-8250-ae9d8990efe4':
        assert data['startupOpen'] and data['startupSelected'] == startup
        assert any(call['url'] == '/api/local-summaries?task_id=' + startup for call in data['initialCalls'])
    elif startup is None:
        assert data['startupOpen'] and not data['startupSelected']
    else:
        assert [call['url'] for call in data['initialCalls']] == ['/api/components']
    assert not any(call.get('method') == 'POST' for call in data['initialCalls'])
    assert 'unavailable for 1 task(s)' in data['initialStatus']
    if active:
        assert data['listed'] == [{'title': '<script>Literal task title</script>',
                                   'context': '70.0% context · 210,000 / 300,000 input/window tokens'}]
        assert data['selected'] == 'a6e593dc-4bd7-40f6-8250-ae9d8990efe4'
        assert data['focused'] and data['inferenceReady']
        assert data['summary'] == 'Saved summary'
    else:
        assert not data['listed']
        assert 'Turn on LangMem and llama.cpp' in data['initialStatus']
    assert data['postsBeforeSave'] == []
    assert data['retained'] == '80'
    assert data['invalidPosts'] == 0 and '20% to 95%' in data['invalidMessage']
    assert len(data['posts']) == 1
    assert data['posts'][0]['url'] == '/api/summary-reminders'
    assert data['posts'][0]['headers']['X-Codex-Update-Token'] == 'csrf-fixture'
    assert json.loads(data['posts'][0]['body']) == {'enabled': False, 'threshold_percent': 80}
    assert data['saved'] and data['hiddenPolls'] == 0
