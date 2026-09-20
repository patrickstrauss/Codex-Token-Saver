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
        el('saved').textContent = savings.available ? number(savings.saved_tokens) : 'Unavailable';
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
            ? 'Last recorded savings: ' + new Date(savings.last_recorded_at).toLocaleString()
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
    setInterval(loadStatus, 5000);
    render();
    loadStatus();
})();
