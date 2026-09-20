"""Exercise the actual dashboard JavaScript with an isolated DOM surface."""
import json
import shutil
import subprocess

import pytest

import app


@pytest.mark.skipif(shutil.which('node') is None, reason='JavaScript rendering check requires Node')
def test_desktop_card_renders_signed_savings_and_never_claims_runtime_activity():
    script = app.HTML.split('<script>', 1)[1].split('</script>', 1)[0]
    harness = r'''
const vm = require('node:vm');
const source = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const nodes = {};
function node(id) { return nodes[id] ||= {style: {}, textContent: '', innerHTML: '', scrollTop: 0}; }
const context = {document: {getElementById: node, querySelector: node}, EventSource: function() {}, setInterval() {}, console};
vm.createContext(context);
vm.runInContext(source, context);
context.updateDashboard({desktop_headroom: {configured: true, data_status: 'recorded', total_saved: -120, gross_saved: 300, retrieval_tokens: 400, read_count: 2, retrieve_count: 1, last_recorded_at: '2026-09-13T05:52:00Z'}});
const recorded = JSON.parse(JSON.stringify(nodes));
context.updateDashboard({desktop_headroom: {configured: true, data_status: 'unavailable', total_saved: null}});
const unavailable = JSON.parse(JSON.stringify(nodes));
context.updateDashboard({desktop_headroom: {configured: false, data_status: 'empty', total_saved: 0, gross_saved: 0, retrieval_tokens: 0, read_count: 0, retrieve_count: 0}});
process.stdout.write(JSON.stringify({recorded, unavailable, unconfigured: nodes}));
'''
    result = subprocess.run(['node', '-e', harness], input=json.dumps(script), text=True,
                            capture_output=True, check=True, timeout=10)
    states = json.loads(result.stdout)
    recorded = states['recorded']
    assert recorded['desktop-headroom-value']['textContent'] == '-120'
    assert 'net content' in recorded['desktop-headroom-sub']['textContent']
    assert '2 reads' in recorded['desktop-headroom-stats']['textContent']
    assert '1 retrieval' in recorded['desktop-headroom-stats']['textContent']
    assert '300' in recorded['desktop-headroom-detail']['textContent']
    assert '400' in recorded['desktop-headroom-detail']['textContent']
    assert recorded['desktop-headroom-version']['textContent'] == 'Configured'
    assert 'Local file tools configured' in recorded['desktop-headroom-status']['textContent']
    assert 'active' not in recorded['desktop-headroom-status']['textContent'].lower()
    assert states['unavailable']['desktop-headroom-value']['textContent'] == '--'
    assert 'unavailable' in states['unavailable']['desktop-headroom-stats']['textContent']
    assert states['unconfigured']['desktop-headroom-version']['textContent'] == 'Not configured'
    assert states['unconfigured']['desktop-headroom-value']['textContent'] == '0'
    assert 'no file or command reductions recorded' in states['unconfigured']['desktop-headroom-stats']['textContent']


@pytest.mark.skipif(shutil.which('node') is None, reason='JavaScript rendering check requires Node')
def test_running_to_offline_states_keep_history_and_clear_live_status():
    script = app.HTML.split('<script>', 1)[1].split('</script>', 1)[0]
    harness = r'''
const vm = require('node:vm');
const source = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const nodes = {};
function node(id) { return nodes[id] ||= {style: {}, textContent: '', innerHTML: '', scrollTop: 0}; }
const context = {
    document: {getElementById: node, querySelector: node},
    EventSource: function() {}, setInterval() {}, console
};
vm.createContext(context);
vm.runInContext(source, context);
context.updateDashboard({overall_health: 'ok', rtk: {active: true, total_saved: 100}, headroom: {active: true, health: 'ok', total_saved: 234, requests_total: 3}});
context.updateDashboard({overall_health: 'ok', rtk: {active: true, total_saved: 100}, headroom: {active: false, health: 'inactive', total_saved: 234, data_status: 'historical', source: 'savings_events.jsonl', last_recorded_at: '2026-09-13T05:50:47+00:00'}});
const historical = JSON.parse(JSON.stringify(nodes));
context.updateDashboard({overall_health: 'stale', rtk: {active: false, health: 'stale', total_saved: 100, data_status: 'historical'}, headroom: {active: false, health: 'inactive', total_saved: null, data_status: 'unavailable'}});
process.stdout.write(JSON.stringify({historical, unavailable: nodes}));
'''
    result = subprocess.run(['node', '-e', harness], input=json.dumps(script), text=True,
                            capture_output=True, check=True, timeout=10)
    states = json.loads(result.stdout)
    historical = states['historical']
    assert historical['headroom-value']['textContent'] == '234'
    assert 'last recorded' in historical['headroom-sub']['textContent']
    assert 'offline' in historical['headroom-sub']['textContent']
    assert historical['headroom-health']['className'] == 'health-dot health-inactive'
    assert historical['health-pulse']['className'] == 'pulse-dot'
    assert historical['headroom-bar']['style']['width'] == '0%'
    unavailable = states['unavailable']
    assert unavailable['headroom-value']['textContent'] == '--'
    assert 'no recorded data' in unavailable['headroom-sub']['textContent']
    assert unavailable['rtk-value']['textContent'] == '100'
    assert 'records unavailable' in unavailable['rtk-sub']['textContent']
    assert unavailable['rtk-stats']['textContent'] == 'Unable to read RTK history'
    assert unavailable['health-pulse']['className'] == 'pulse-dot health-stale'


@pytest.mark.skipif(shutil.which('node') is None, reason='JavaScript rendering check requires Node')
def test_headroom_coverage_explains_skips_without_counting_checks_as_savings():
    script = app.HTML.split('<script>', 1)[1].split('</script>', 1)[0]
    harness = r'''
const vm = require('node:vm');
const source = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const nodes = {};
function node(id) { return nodes[id] ||= {style: {}, textContent: '', innerHTML: '', scrollTop: 0}; }
const context = {document: {getElementById: node, querySelector: node}, EventSource: function() {}, setInterval() {}, console};
vm.createContext(context);
vm.runInContext(source, context);
context.updateDashboard({desktop_headroom: {configured: true, total_saved: 0, data_status: 'empty', automation: {
    data_status: 'recorded', observed: 190, rewritten: 1, skipped: 189,
    top_skip_reasons: [{label: 'scripts, pipelines or unsupported syntax', count: 176}]
}}});
const observed = JSON.parse(JSON.stringify(nodes));
context.updateDashboard({desktop_headroom: {configured: true, total_saved: 0, automation: {data_status: 'unavailable', observed: null}}});
const unavailable = JSON.parse(JSON.stringify(nodes));
context.updateDashboard({desktop_headroom: {configured: true, total_saved: 0, automation: {configured: true, data_status: 'empty', observed: 0}}});
process.stdout.write(JSON.stringify({observed, unavailable, empty: nodes}));
'''
    result = subprocess.run(['node', '-e', harness], input=json.dumps(script), text=True,
                            capture_output=True, check=True, timeout=10)
    states = json.loads(result.stdout)
    observed = states['observed']
    assert observed['desktop-headroom-value']['textContent'] == '0'
    assert 'selected command outputs' in observed['desktop-headroom-scope']['textContent']
    assert 'request savings are tracked separately below' in observed['desktop-headroom-scope']['textContent']
    assert '190 checked / 1 wrapped / 189 skipped' in observed['desktop-headroom-status']['textContent']
    assert 'Wrapping does not guarantee savings' in observed['desktop-headroom-status']['textContent']
    assert observed['desktop-headroom-skips']['textContent'] == 'Top skips in recent log: scripts, pipelines or unsupported syntax (176).'
    assert states['unavailable']['desktop-headroom-status']['textContent'] == 'Hook observations unavailable.'
    assert states['unavailable']['desktop-headroom-skips']['textContent'] == ''
    assert 'no events yet' in states['empty']['desktop-headroom-status']['textContent']


@pytest.mark.skipif(shutil.which('node') is None, reason='JavaScript rendering check requires Node')
def test_new_zero_savings_check_updates_explanation_without_increasing_saved_total():
    script = app.HTML.split('<script>', 1)[1].split('</script>', 1)[0]
    harness = r'''
const vm = require('node:vm');
const source = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const nodes = {};
function node(id) { return nodes[id] ||= {style: {}, textContent: '', innerHTML: '', scrollTop: 0}; }
const context = {document: {getElementById: node, querySelector: node}, EventSource: function() {}, setInterval() {}, console};
vm.createContext(context);
vm.runInContext(source, context);
const desktop = {configured: true, data_status: 'recorded', total_saved: 2000, gross_saved: 2000,
    retrieval_tokens: 0, read_count: 0, command_count: 1, retrieve_count: 0,
    last_recorded_at: '2026-09-13T14:00:00Z', command_attempt_count: 1,
    last_command_check: '2026-09-13T14:00:00Z', last_command_status: 'compressed', command_statuses: {compressed: 1}};
context.updateDashboard({desktop_headroom: desktop});
const earlier = JSON.parse(JSON.stringify(nodes));
context.updateDashboard({desktop_headroom: {...desktop, command_attempt_count: 7,
    last_command_check: '2026-09-13T15:00:00Z', last_command_status: 'no_reduction',
    command_statuses: {compressed: 1, small_output: 2, no_reduction: 2, command_failed: 1, exact_requested: 1}}});
const latest = JSON.parse(JSON.stringify(nodes));
const passthrough = {};
for (const status of ['compression_timeout', 'streaming_timeout', 'inherited_pipe', 'interactive_passthrough']) {
    context.updateDashboard({desktop_headroom: {...desktop, last_command_status: status, command_statuses: {[status]: 1}}});
    passthrough[status] = {check: nodes['desktop-headroom-check'].textContent, outcomes: nodes['desktop-headroom-outcomes'].textContent};
}
context.updateDashboard({desktop_headroom: {configured: true, data_status: 'unavailable', total_saved: null}});
process.stdout.write(JSON.stringify({earlier, latest, passthrough, unavailable: nodes}));
'''
    result = subprocess.run(['node', '-e', harness], input=json.dumps(script), text=True,
                            capture_output=True, check=True, timeout=10)
    states = json.loads(result.stdout)
    earlier, latest = states['earlier'], states['latest']
    assert latest['desktop-headroom-value']['textContent'] == earlier['desktop-headroom-value']['textContent'] == '2.0K'
    assert latest.get('desktop-headroom-check', {}).get('textContent') != earlier.get('desktop-headroom-check', {}).get('textContent')
    assert 'Last output check:' in latest['desktop-headroom-check']['textContent']
    assert 'original kept; no further reduction' in latest['desktop-headroom-check']['textContent']
    assert '7 outputs checked' in latest['desktop-headroom-outcomes']['textContent']
    for expected in ['1 compressed', '2 too small', '2 no further reduction', '1 failed', '1 exact requested']:
        assert expected in latest['desktop-headroom-outcomes']['textContent']
    assert latest['desktop-headroom-recorded']['textContent'].startswith('Last savings ledger event:')
    assert latest['desktop-headroom-recorded']['textContent'] == earlier['desktop-headroom-recorded']['textContent']
    assert states['unavailable']['desktop-headroom-check']['textContent'] == 'Output-check records unavailable.'
    assert states['unavailable']['desktop-headroom-outcomes']['textContent'] == ''
    for status, explanation in [('compression_timeout', 'compression timed out'),
                                ('streaming_timeout', 'output streamed directly'),
                                ('inherited_pipe', 'child process kept output open'),
                                ('interactive_passthrough', 'interactive command')]:
        assert explanation in states['passthrough'][status]['check']
        assert 'other' not in states['passthrough'][status]['outcomes']
