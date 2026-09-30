"""Exercise shipped rendering and filter requests with hostile title text."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Requires Node')
def test_filters_refresh_activity_preserve_selection_and_clear_stale_rows():
    path = Path(__file__).parents[1] / 'static/activity.js'
    assert path.exists(), 'Activity renderer is missing'
    harness = r'''
const vm=require('node:vm'), fixture=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const nodes={}, calls=[], timers=[]; let serial=0, broken=false, pending=null, hold=false;
function node(id){return nodes[id] ||= {value:'',textContent:'',children:[],listeners:{},hidden:false,
 append(...items){this.children.push(...items)},replaceChildren(...items){this.children=items},
 addEventListener(key,fn){this.listeners[key]=fn},setAttribute(){}}}
const task='a6e593dc-4bd7-40f6-8250-ae9d8990efe4';
const data={data_status:'recorded',total:2,groups:{all:2,tasks:1,unknown:1,diagnostic:0,informational:0},
 tasks:[{task_id:task,title:'<img src=x onerror=alert(1)>',count:1}],outcomes:{completed:1,failed:1,blocked:0,bypassed:0},
 retention_limit:2000,failure_categories:{timeout:1},bypass_reasons:{},
 recent:[{timestamp:'2026-09-30T01:00:00Z',component:'serena',outcome:'failed',kind:'operation',task_id:task,error_code:'timeout'}],
 hook_coverage:{scope:'all',status:'observed',data_status:'recorded',observed:5,rewritten:2,skipped:3,top_skip_reasons:[{label:'unsupported syntax',count:3}]}};
const context={document:{getElementById:node,createElement:()=>node('new-'+serial++),hidden:false},
 setInterval(fn){timers.push(fn)},URLSearchParams,
 fetch:async(url)=>{calls.push(url);if(hold)return new Promise(resolve=>pending=resolve);return {ok:!broken,json:async()=>data}}};
vm.createContext(context);vm.runInContext(fixture.source,context);
async function flush(){for(let i=0;i<25;i++)await Promise.resolve()}
function texts(item){return [item.textContent,...item.children.flatMap(texts)].join(' ')}
(async()=>{await flush();const initial={summary:node('activity-summary').textContent,rows:texts(node('activity-recent')),hook:node('activity-hook').textContent,options:texts(node('activity-task'))};
 node('activity-task').value=task;node('activity-task').listeners.change();await flush();
 const filtered=calls.at(-1),selected=node('activity-task').value;
 node('activity-group').value='diagnostic';node('activity-group').listeners.change();await flush();const diagnostic=calls.at(-1);
 hold=true;const refreshing=node('activity-refresh').listeners.click();await flush();
 hold=false;node('activity-group').value='unknown';node('activity-group').listeners.change();await flush();
 pending({ok:true,json:async()=>data});await refreshing;await flush();const afterRace=calls.at(-1);
 broken=true;node('activity-refresh').listeners.click();await flush();
 const error=node('activity-error').textContent,remaining=node('activity-recent').children.length;
 context.document.hidden=true;const before=calls.length;timers[0]();await flush();
 process.stdout.write(JSON.stringify({initial,filtered,diagnostic,selected,afterRace,error,remaining,hiddenPolls:calls.length-before,calls}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1});
'''
    result = subprocess.run(['node', '-e', harness], input=json.dumps({'source': path.read_text(encoding='utf-8')}),
                            capture_output=True, text=True, timeout=10, check=True)
    data = json.loads(result.stdout)
    assert '1 completed' in data['initial']['summary']
    assert 'timeout' in data['initial']['rows']
    assert '<img src=x onerror=alert(1)>' in data['initial']['options']
    assert '5 observed' in data['initial']['hook'] and '3 bypassed' in data['initial']['hook']
    assert 'unsupported syntax' in data['initial']['hook']
    assert 'task_id=a6e593dc' in data['filtered'] and data['selected'].startswith('a6e593dc')
    assert 'group=diagnostic' in data['diagnostic']
    assert 'group=unknown' in data['afterRace'] and 'task_id=' not in data['afterRace']
    assert data['error'] and data['remaining'] == 0 and data['hiddenPolls'] == 0
    assert all(url.startswith('/api/activity') for url in data['calls'])
