/* New metadata only. This renderer never reads or changes savings. */
(function () {
    'use strict';
    function el(id) { return document.getElementById(id); }
    if (!el('bundle-activity')) return;
    var generation = 0, reading = false;
    var group = el('activity-group'), task = el('activity-task');
    function node(tag, text) { var value = document.createElement(tag); value.textContent = text; return value; }
    function date(value) { var parsed = new Date(value); return value && !isNaN(parsed.getTime()) ? parsed.toLocaleString() : 'Not recorded'; }
    function categories(values) { return Object.entries(values || {}).map(function (item) { return item[0] + ': ' + item[1]; }).join(' · ') || 'None recorded'; }
    function render(data) {
        var selected = task.value, titles = {}, choices = [node('option', 'All tasks')]; choices[0].value = '';
        (data.tasks || []).forEach(function (item) {
            titles[item.task_id] = item.title || item.task_id;
            var option = node('option', (item.title ? item.title + ' · ' : '') + item.task_id);
            option.value = item.task_id; choices.push(option);
        });
        if (selected && !titles[selected]) { var old = node('option', selected); old.value = selected; choices.push(old); }
        task.replaceChildren.apply(task, choices); task.value = selected;
        var outcomes = data.outcomes || {};
        el('activity-summary').textContent = data.data_status === 'unavailable' ? 'Activity storage is unavailable.'
            : !data.total ? 'No new activity in this selection.' : data.total + ' retained events · '
            + ['completed', 'failed', 'blocked', 'bypassed'].map(function (key) { return (outcomes[key] || 0) + ' ' + key; }).join(' / ');
        el('activity-groups').textContent = 'All retained records: ' + categories(data.groups) + ' · Maximum ' + data.retention_limit + ' events. Task and unknown groups contain operations; diagnostic and informational records have their own groups.';
        el('activity-failures').textContent = 'Failure / blocked categories: ' + categories(data.failure_categories) + ' · Bypass reasons: ' + categories(data.bypass_reasons);
        var hook = data.hook_coverage || {}, scope = hook.scope === 'task' ? 'Selected task' : hook.scope === 'unknown' ? 'Unknown tasks' : 'All tasks';
        el('activity-hook').textContent = hook.data_status === 'unavailable' || !hook.status ? scope + ': hook observations unavailable.'
            : !hook.observed ? scope + ': no hook events observed in this window.' + (hook.configured ? ' Configured; awaiting an observed event.' : ' Hook not configured.')
            : scope + ': ' + hook.observed + ' observed · ' + hook.rewritten + ' rewritten · ' + hook.skipped + ' bypassed. '
                + (hook.top_skip_reasons || []).map(function (item) { return item.count + ' ' + item.label; }).join(' · ');
        var rows = (data.recent || []).map(function (event) {
            var row = document.createElement('tr');
            [date(event.timestamp), event.component, event.outcome + (event.error_code ? ' / ' + event.error_code : ''), event.kind,
                event.task_id ? titles[event.task_id] || event.task_id : 'Unknown task'].forEach(function (value) { row.append(node('td', value)); });
            return row;
        });
        el('activity-recent').replaceChildren.apply(el('activity-recent'), rows);
    }
    async function load() {
        if (document.hidden) return;
        var current = ++generation, query = new URLSearchParams({group: group.value || 'all'});
        if (task.value) query.set('task_id', task.value);
        reading = true;
        el('activity-error').hidden = true;
        try {
            var response = await fetch('/api/activity?' + query.toString(), {credentials: 'same-origin', cache: 'no-store'});
            if (!response.ok) throw new Error();
            var data = await response.json();
            if (current === generation) render(data);
        } catch (_) {
            if (current === generation) {
                el('activity-error').textContent = 'Activity could not be loaded. Refresh to try again.';
                el('activity-error').hidden = false;
                el('activity-summary').textContent = 'Activity unavailable.';
                el('activity-groups').textContent = '';
                el('activity-failures').textContent = '';
                el('activity-hook').textContent = 'Hook observations unavailable.';
                el('activity-recent').replaceChildren();
            }
        } finally { if (current === generation) reading = false; }
    }
    group.addEventListener('change', function () { task.disabled = group.value === 'unknown'; if (task.disabled) task.value = ''; return load(); });
    task.addEventListener('change', load);
    el('activity-refresh').addEventListener('click', load);
    setInterval(function () { if (!reading) load(); }, 15000);
    load();
})();
