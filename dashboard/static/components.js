/* Explicit component choices. Reads never start models or alter routing. */
(function () {
    'use strict';
    if (!document.getElementById('bundle-components')) return;
    var token = document.querySelector('meta[name="bundle-update-token"]').content;
    var state = {}, rows = {}, changing = false, reading = false, generation = 0;
    var names = ['rtk', 'headroom_local', 'headroom_requests', 'serena', 'playwright_cli', 'ast_grep', 'laya_router'];
    var labels = ['Command output', 'Local file & output reading', 'Request compression', 'Code navigation', 'Browser automation', 'Structural code search', 'Bundle tool router'];
    var engines = ['RTK', 'Headroom · local output', 'Headroom · model requests', 'Serena · symbol tools', 'Playwright CLI', 'ast-grep', 'Laya · local classifier'];
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
        title.append(textNode('span', 'component-engine', engines[i]));
        var input = document.createElement('input'); input.type = 'checkbox'; input.id = 'component-' + name;
        input.setAttribute('role', 'switch'); input.setAttribute('aria-label', labels[i]); input.disabled = true;
        var choice = textNode('span', '', 'Loading'); label.append(input, choice); top.append(title, label);
        var status = textNode('span', 'component-state', 'Checking'), reason = textNode('p', 'component-reason');
        var used = textNode('p', 'component-use'), diagnostic = textNode('p', 'component-use'), problem = textNode('p', 'component-reason component-error');
        box.append(top, status, reason, used, diagnostic, problem); el('components-list').append(box);
        rows[name] = {input:input, choice:choice, status:status, reason:reason, used:used, diagnostic:diagnostic, problem:problem};
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
            if (component.activity) row.used.textContent += ' · Legacy mixed counters: ' + (component.activity.completed || 0) + ' completed / '
                + (component.activity.failed || 0) + ' failed / ' + (component.activity.blocked || 0) + ' blocked'
                + ' / ' + (component.activity.informational || 0) + ' informational / ' + (component.activity.diagnostic || 0) + ' diagnostic. No task attribution or backfill.';
            var diagnostic = component.diagnostics || {}, details = [];
            if (component.id === 'laya_router' || component.last_verified_call) details.push('Last verified operation: ' + date(component.last_verified_call));
            if (diagnostic.last_elapsed_ms != null) details.push('Last tool duration: ' + diagnostic.last_elapsed_ms + ' ms'
                + (diagnostic.last_tool ? ' (' + diagnostic.last_tool + ')' : ''));
            if (diagnostic.last_failure) details.push('Last recorded failure: ' + diagnostic.last_failure
                + (diagnostic.last_failure_code ? ' (' + diagnostic.last_failure_code + ')' : '') + ' · ' + date(diagnostic.last_failure_at));
            row.diagnostic.textContent = details.join(' · ');
            row.diagnostic.hidden = !details.length;
            row.problem.textContent = component.last_error || (component.restart_required ? 'Reload Codex for newly configured tools or connections. Already-loaded tasks can retain their old configuration.' : '');
        });
        el('components-health').textContent = changing ? 'Applying preference...' : state.overall_health === 'ok'
            ? (state.unverified_count ? state.selected_count + ' selected · ' + state.unverified_count + ' tool connection(s) unverified'
                : state.selected_count ? state.selected_count + ' selected components ready' : 'All components are Off')
            : state.overall_health ? 'A selected component needs attention' : 'Checking selected components...';
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
    var disableOpening = false;
    el('bundle-disable').addEventListener('click', async function () {
        if (disableOpening) return;
        disableOpening = true; this.disabled = true;
        error('bundle-disable-error', ''); el('bundle-disable-status').hidden = true;
        try {
            var response = await fetch('/api/bundle/disable', {method:'POST', credentials:'same-origin', cache:'no-store',
                headers:{'Content-Type':'application/json', 'X-Codex-Update-Token':token}, body:JSON.stringify({action:'open'})});
            var data = await response.json();
            if (!response.ok) throw new Error(data.error || 'The disable window could not open.');
            el('bundle-disable-status').textContent = data.already_open
                ? 'The disable window is already open. Check the Windows taskbar to continue or cancel.'
                : 'The Windows confirmation window is opening. Nothing is disabled until you confirm there.';
            el('bundle-disable-status').hidden = false;
        } catch (problem) {
            error('bundle-disable-error', problem.message || 'Could not open the disable window. Run Disable-Token-Saver.cmd from the installed folder.');
        } finally { disableOpening = false; this.disabled = false; }
    });
    setInterval(load, 10000);
    load();
})();
