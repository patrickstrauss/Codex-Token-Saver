/* Display independent request savings. Mutations happen only on an explicit click. */
(function () {
    'use strict';
    if (!document.getElementById('request-proxy')) return;
    var token = document.querySelector('meta[name="bundle-update-token"]').content;
    var state = {}, reading = false, changing = false, sequence = 0, errorMessage = '';
    function el(id) { return document.getElementById('request-proxy-' + id); }
    function number(value) { return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : 'Unavailable'; }
    function render() {
        var modes = {optimized: 'Optimized connection', direct: 'Direct connection — compression unavailable',
            offline: 'Request connection offline', paused: 'Request compression paused'};
        el('status').textContent = changing ? 'Applying request compression setting...' : modes[state.mode] || 'Checking desktop connection...';
        el('enable').disabled = changing || !state.installed || !state.validated || (state.enabled && state.route_enabled);
        el('pause').disabled = changing || !(state.enabled || state.route_enabled);
        var savings = state.savings || {}, requests = state.requests || {};
        var recent = state.recent_savings, key = el('window').value || 'fifteen_minutes';
        var selected = key !== 'lifetime' ? ((recent && recent.windows) || {})[key] || {} : savings;
        var available = key !== 'lifetime' ? recent && recent.available : savings.available;
        var label = key !== 'lifetime' ? ({fifteen_minutes:'last 15 minutes', today:'today', seven_days:'last 7 days'}[key]) : 'lifetime';
        el('saved').textContent = available ? number(selected.saved_tokens) : 'Unavailable';
        el('scope').textContent = 'Estimated input tokens avoided · ' + label + ' · all tasks. Individual-task attribution is unavailable.';
        el('window-detail').textContent = available ? number(selected.requests)
            + (key === 'lifetime' ? ' requests recorded' : ' savings events in this window')
            + (selected.reduction_pct == null ? '' : ' · ' + number(selected.reduction_pct) + '% reduction within recorded events') : 'No readable records for this window.';
        el('coverage').textContent = key !== 'lifetime' && recent && recent.available
            ? 'Headroom records positive-savings events only; zero-savings requests and expansions are excluded. This is not an overall traffic reduction rate.'
                + (!recent.complete ? ' Partial ledger coverage: older or invalid records were omitted. These are totals from available records only.' : '') : '';
        el('counts').textContent = 'Requests recorded by Headroom: ' + number(savings.requests)
            + '. Completed connections: ' + number(requests.optimized) + ' optimized; ' + number(requests.direct)
            + ' direct; ' + number(requests.failed) + ' failed. Active connections: ' + number(requests.active);
        el('routing').textContent = state.route_enabled
            ? 'Codex is configured to use this request connection.'
            : 'Codex is configured for its normal connection. Loaded tasks may retain their previous connection until restarted.';
        el('backend').textContent = !state.installed ? 'Request compression has not been installed.'
            : !state.validated ? 'Request compression is waiting for validation.'
            : state.backend_ready ? 'Headroom compression engine is ready.'
            : state.ready ? 'Headroom is warming up or unavailable. New requests can use the direct connection.'
            : 'The local request connection is unavailable. Check the background app.';
        el('recorded').textContent = savings.last_recorded_at
            ? 'Last recorded request activity: ' + new Date(savings.last_recorded_at).toLocaleString()
            : 'No request savings recorded yet';
        el('error').textContent = errorMessage || state.last_error || '';
        el('error').hidden = !el('error').textContent;
        el('restart').hidden = !state.restart_required;
        el('restart').textContent = state.restart_required
            ? 'Restart Codex when convenient to apply the connection change to tasks already loaded. You can continue existing tasks after restarting.' : '';
    }
    async function loadStatus() {
        if (reading || changing || document.hidden) return;
        reading = true;
        var requestId = ++sequence;
        try {
            var response = await fetch('/api/request-proxy', {credentials: 'same-origin', cache: 'no-store'});
            var data = await response.json();
            if (requestId !== sequence) return;
            if (!response.ok) throw new Error('Request compression status is unavailable.');
            state = data;
            errorMessage = '';
        } catch (error) {
            if (requestId === sequence) errorMessage = 'Request compression status is unavailable. The displayed counters may be stale.';
        } finally {
            reading = false;
            render();
        }
    }
    async function change(action) {
        if (changing) return;
        changing = true;
        ++sequence;
        errorMessage = '';
        render();
        try {
            var response = await fetch('/api/request-proxy', {
                method: 'POST', credentials: 'same-origin', cache: 'no-store',
                headers: {'Content-Type': 'application/json', 'X-Codex-Update-Token': token},
                body: JSON.stringify({action: action})
            });
            var data = await response.json();
            if (response.ok) state = data;
            else errorMessage = data.error || 'The setting could not be changed. Check the current state.';
        } catch (error) {
            errorMessage = 'The response was interrupted. Check the current state before trying again.';
        } finally {
            changing = false;
            render();
        }
    }
    el('enable').addEventListener('click', function () { change('enable'); });
    el('pause').addEventListener('click', function () { change('pause'); });
    el('window').addEventListener('change', render);
    setInterval(loadStatus, 5000);
    render();
    loadStatus();
})();
