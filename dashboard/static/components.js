/* Explicit component choices. Reads never start models or alter routing. */
(function () {
    'use strict';
    if (!document.getElementById('bundle-components')) return;
    var token = document.querySelector('meta[name="bundle-update-token"]').content;
    var state = {}, rows = {}, changing = false, reading = false, generation = 0;
    var names = ['rtk', 'headroom_local', 'headroom_requests', 'serena', 'local_summaries', 'llama_cpp'];
    var labels = ['RTK command filtering', 'Headroom local output', 'Headroom request compression', 'Serena symbol navigation', 'LangMem local summaries', 'llama.cpp local inference'];
    var states = {off:'Off', ready:'Ready', configured:'Configured · task loading unverified', in_use:'In use', bypassed:'Bypassed', needs_restart:'Needs setup / reload', error:'Error', unavailable:'Unavailable'};
    function el(id) { return document.getElementById(id); }
    function textNode(tag, className, text) {
        var node = document.createElement(tag); node.className = className; node.textContent = text || ''; return node;
    }
    function date(value) { var d = new Date(value); return value && !isNaN(d.getTime()) ? d.toLocaleString() : 'Not recorded'; }
    function error(id, message) { el(id).textContent = message || ''; el(id).hidden = !message; }
    names.forEach(function (name, i) {
        var box = textNode('article', 'component-row'), top = textNode('div', 'component-top');
        var title = textNode('span', 'component-name', labels[i]), label = textNode('label', 'component-toggle');
        var input = document.createElement('input'); input.type = 'checkbox'; input.id = 'component-' + name;
        input.setAttribute('role', 'switch'); input.setAttribute('aria-label', labels[i]); input.disabled = true;
        var choice = textNode('span', '', 'Loading'); label.append(input, choice); top.append(title, label);
        var status = textNode('span', 'component-state', 'Checking'), reason = textNode('p', 'component-reason');
        var used = textNode('p', 'component-use'), problem = textNode('p', 'component-reason component-error');
        box.append(top, status, reason, used, problem); el('components-list').append(box);
        rows[name] = {input:input, choice:choice, status:status, reason:reason, used:used, problem:problem};
        input.addEventListener('change', function () { change(name, input.checked); });
    });
    function render() {
        (state.components || []).forEach(function (component) {
            var row = rows[component.id]; if (!row) return;
            row.input.checked = !!component.requested_enabled;
            row.input.disabled = changing || (!component.available && !component.requested_enabled);
            row.choice.textContent = component.requested_enabled == null ? 'Unknown' : component.requested_enabled ? 'On' : 'Off';
            row.status.textContent = states[component.state] || 'Unknown';
            row.status.dataset.state = component.state || 'error';
            row.reason.textContent = component.reason || '';
            row.used.textContent = 'Last recorded use: ' + date(component.last_use);
            if (component.activity) row.used.textContent += ' · ' + (component.activity.completed || 0) + ' completed / '
                + (component.activity.failed || 0) + ' failed / ' + (component.activity.blocked || 0) + ' blocked calls';
            row.problem.textContent = component.last_error || (component.restart_required ? 'Reload Codex for newly configured tools or connections. Already-loaded tasks can retain their old configuration.' : '');
        });
        el('components-health').textContent = changing ? 'Applying preference...' : state.overall_health === 'ok'
            ? (state.unverified_count ? state.selected_count + ' selected · ' + state.unverified_count + ' tool connection(s) unverified'
                : state.selected_count ? state.selected_count + ' selected components ready' : 'All components are Off')
            : state.overall_health ? 'A selected component needs attention' : 'Checking selected components...';
        summaryButtons();
    }
    async function load() {
        if (reading || changing || document.hidden) return;
        reading = true; var current = ++generation;
        try {
            var response = await fetch('/api/components', {credentials:'same-origin', cache:'no-store'}), data = await response.json();
            if (current !== generation) return;
            if (!response.ok) throw new Error();
            state = data; error('components-error', '');
        } catch (_) {
            if (current === generation) error('components-error', 'Component status is unavailable. Displayed state may be stale.');
        } finally { reading = false; render(); }
    }
    async function change(component, enabled) {
        if (changing) return;
        changing = true; ++generation; error('components-error', ''); render();
        try {
            var response = await fetch('/api/components', {method:'POST', credentials:'same-origin', cache:'no-store',
                headers:{'Content-Type':'application/json', 'X-Codex-Update-Token':token},
                body:JSON.stringify({component:component, enabled:enabled})});
            var data = await response.json();
            if (response.ok) {
                state = data;
                var changed = data.change || {};
                el('components-notice').textContent = changed.restart_required
                    ? labels[names.indexOf(component)] + ': configuration changed. Reload Codex when convenient to refresh tools or connections; already-loaded tasks can retain their prior configuration.' : '';
                el('components-notice').hidden = !changed.restart_required;
            }
            else error('components-error', data.error || 'The preference could not be changed.');
        } catch (_) { error('components-error', 'The response was interrupted. Refresh status before trying again.'); }
        finally { changing = false; render(); }
    }
    var summaryBusy = false, summaryState = {}, selectedTask = '', summaryGeneration = 0;
    function summaryButtons() {
        var ready = ['local_summaries', 'llama_cpp'].every(function (name) {
            return (state.components || []).some(function (component) { return component.id === name && component.effective_enabled; });
        });
        el('local-summary-refresh').disabled = summaryBusy || !selectedTask || !summaryState.available || !!summaryState.running || !ready;
        el('local-summary-cancel').disabled = summaryBusy || !summaryState.running || !(summaryState.job || {}).task_id;
        el('local-summary-reload').disabled = summaryBusy;
    }
    async function tasks() {
        if (summaryBusy || !el('local-summary-panel').open || document.hidden) return;
        try {
            var response = await fetch('/api/local-summaries', {credentials:'same-origin', cache:'no-store'}), data = await response.json();
            if (!response.ok) throw new Error();
            summaryState = data.status || {};
            error('local-summary-error', summaryState.last_error || (summaryState.job || {}).error || '');
            var select = el('local-summary-task'); select.replaceChildren(new Option('Choose a task...', ''));
            (data.tasks || []).forEach(function (task) {
                select.append(new Option((task.project || 'Task') + ' · ' + task.task_id + ' · ' + date(task.updated_at), task.task_id));
            });
            select.value = selectedTask;
            if (select.value !== selectedTask) selectedTask = '';
            el('local-summary-status').textContent = summaryState.running ? 'A local summary job is running.'
                : summaryState.available ? 'Ready for an explicit summary request. Both LangMem and llama.cpp must be On.'
                : 'Local summary runtime is unavailable. Check the component controls.';
            summaryButtons();
        } catch (_) { error('local-summary-error', 'Task list is unavailable. Original conversations are unchanged.'); }
    }
    async function readSummary() {
        var task = selectedTask, current = ++summaryGeneration;
        if (!task) { el('local-summary-text').textContent = 'Select a task to view its saved summary.'; el('local-summary-coverage').textContent = ''; el('local-summary-quality').textContent = ''; return; }
        try {
            var response = await fetch('/api/local-summaries?task_id=' + encodeURIComponent(task), {credentials:'same-origin', cache:'no-store'}), data = await response.json();
            if (current !== summaryGeneration || task !== selectedTask) return;
            if (!response.ok) throw new Error();
            el('local-summary-text').textContent = data.summary || 'No saved summary yet. Choose Refresh summary to generate one locally.';
            var coverage = data.coverage || {}, metrics = data.metrics || {};
            var incomplete = [];
            if (coverage.source_incomplete) incomplete.push('An unfinished transcript record was not read.');
            if (coverage.incomplete_tool_pairs) incomplete.push(coverage.incomplete_tool_pairs + ' tool calls have no matching result.');
            if (coverage.source_truncated) incomplete.push('Source inspection was bounded; some content was not read.');
            if (coverage.skipped_lines) incomplete.push(coverage.skipped_lines + ' source records were skipped.');
            if (coverage.pending_messages) incomplete.push(coverage.pending_messages + ' readable messages remain unsummarized.');
            var quality = !data.summary ? 'No saved summary yet.'
                : data.status === 'stale' ? 'Stale summary: source messages changed. Regenerate and verify against originals.'
                : data.status === 'partial' || incomplete.length ? 'Partial summary: coverage is incomplete.'
                : data.status === 'summarized' ? 'Summary covers all currently readable messages.'
                : 'Saved summary; completion status is unavailable.';
            el('local-summary-quality').textContent = quality + (incomplete.length ? ' ' + incomplete.join(' ') : '');
            el('local-summary-coverage').textContent = 'Covered ' + (coverage.summarized_messages || 0) + ' of ' + (coverage.total_messages || 0)
                + ' messages; ' + (coverage.pending_messages || 0) + ' pending.'
                + (typeof metrics.source_tokens === 'number' && typeof metrics.summary_tokens === 'number'
                    ? ' Local text: ' + metrics.source_tokens + ' source tokens → ' + metrics.summary_tokens + ' summary tokens (estimate).' : '');
        } catch (_) { if (current === summaryGeneration) {
            error('local-summary-error', 'Saved summary is unavailable. Try reloading the task.');
            el('local-summary-quality').textContent = 'Summary status is unavailable for the selected task.';
        } }
    }
    async function summaryAction(action) {
        if (summaryBusy) return;
        var task = action === 'cancel' ? (summaryState.job || {}).task_id : selectedTask;
        if (!task) return;
        summaryBusy = true; summaryButtons(); error('local-summary-error', '');
        try {
            var response = await fetch('/api/local-summaries', {method:'POST', credentials:'same-origin', cache:'no-store',
                headers:{'Content-Type':'application/json', 'X-Codex-Update-Token':token}, body:JSON.stringify({action:action, task_id:task})});
            var data = await response.json();
            if (!response.ok) error('local-summary-error', data.error || 'The job could not start.');
        } catch (_) { error('local-summary-error', 'The response was interrupted. Check status before starting another job.'); }
        finally { summaryBusy = false; await tasks(); await readSummary(); summaryButtons(); }
    }
    el('local-summary-panel').addEventListener('toggle', tasks);
    el('local-summary-task').addEventListener('change', function () { selectedTask = this.value; error('local-summary-error', ''); summaryButtons(); readSummary(); });
    el('local-summary-reload').addEventListener('click', tasks);
    el('local-summary-refresh').addEventListener('click', function () { summaryAction('start'); });
    el('local-summary-cancel').addEventListener('click', function () { summaryAction('cancel'); });
    setInterval(function () { if (document.hidden) return; load(); if (el('local-summary-panel').open) { tasks(); if (selectedTask) readSummary(); } }, 10000);
    load();
})();
