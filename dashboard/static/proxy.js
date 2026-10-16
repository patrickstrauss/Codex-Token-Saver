/* Display independent request savings. Mutations happen only on an explicit click. */
(function () {
    'use strict';
    if (!document.getElementById('request-proxy')) return;
    var token = document.querySelector('meta[name="bundle-update-token"]').content;
    var state = {}, reading = false, changing = false, sequence = 0, errorMessage = '', connectionChangedHere = false;
    function el(id) { return document.getElementById('request-proxy-' + id); }
    function number(value) { return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : 'Unavailable'; }
    function percent(value) { return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100 ? number(value) + '%' : 'Unavailable'; }
    function render() {
        el('timing').hidden = false;
        el('rate-note').textContent = 'The first rate covers eligible content and tool schemas; the second includes protected history and uses compression savings only. These are token estimates, not measured Codex quota savings.';
        var modes = {optimized: 'Optimized connection', direct: 'Direct connection — compression unavailable',
            offline: 'Request connection offline', paused: 'Request compression paused'};
        el('status').textContent = changing ? 'Applying request compression setting...' : modes[state.mode] || 'Checking desktop connection...';
        el('enable').disabled = changing || !state.installed || !state.validated || (state.enabled && state.route_enabled);
        el('pause').disabled = changing || !(state.enabled || state.route_enabled);
        var savings = state.savings || {}, requests = state.requests || {};
        var recent = state.recent_savings, label = 'last 24 hours';
        var selected = ((recent && recent.windows) || {}).last_24_hours;
        var available = recent && recent.available && selected;
        selected = selected || {};
        el('saved').textContent = available ? number(selected.saved_tokens) : 'Unavailable';
        el('scope').textContent = 'Estimated input tokens avoided · ' + label + ' · all tasks. Individual-task attribution is unavailable.';
        if (available && !recent.complete) el('scope').textContent += ' Partial record coverage; this total may be incomplete.';
        el('window-detail').textContent = available ? number(selected.requests)
            + ' savings events in this window'
            + (selected.reduction_pct == null ? '' : ' · ' + number(selected.reduction_pct) + '% reduction within recorded events') : 'No readable records for this window.';
        el('coverage').textContent = recent && recent.available
            ? 'Headroom records positive-savings events only; zero-savings requests and expansions are excluded. This is not an overall traffic reduction rate.'
                + (!recent.complete ? ' Partial ledger coverage: older or invalid records were omitted. These are totals from available records only.' : '') : '';
        var metrics = state.backend_metrics || {}, diagnostics = metrics.diagnostics || {};
        el('active-rate').textContent = percent(metrics.active_reduction_pct);
        el('whole-rate').textContent = percent(metrics.whole_reduction_pct);
        el('backend-scope').textContent = 'Current backend counters across all tasks; independent of the 24-hour savings total. Counters reset with backend metrics.'
            + (metrics.collected_at ? ' Snapshot retrieved: ' + new Date(metrics.collected_at).toLocaleString() + '.' : ' Snapshot unavailable.');
        el('diagnostics').textContent = 'WebSocket compression frames: ' + number(diagnostics.frames_attempted)
            + ' attempted; ' + number(diagnostics.frames_compressed) + ' compressed; ' + number(diagnostics.frames_failed)
            + ' failed. Failure reasons are not reported by these counters.';
        el('timing').textContent = 'WebSocket compression time: ' + number(diagnostics.compression_average_ms)
            + ' ms average; ' + number(diagnostics.compression_max_ms) + ' ms slowest; '
            + number(diagnostics.compression_samples) + ' measured. Excludes model generation and upstream connection time.';
        el('counts').textContent = 'Requests recorded by Headroom: ' + number(savings.requests)
            + '. Completed connections: ' + number(requests.optimized) + ' optimized; ' + number(requests.direct)
            + ' direct; ' + number(requests.failed) + ' failed. Active connections: ' + number(requests.active);
        el('routing').textContent = state.route_enabled
            ? 'Codex is configured to use this request connection.'
            : 'Codex is configured for its normal connection. Loaded tasks may retain their previous connection until restarted.';
        if (state.restart_required) el('routing').textContent += ' Already-open tasks can retain an earlier connection. Restart Codex only if a task has not picked up the selected connection.';
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
        // The persisted flag records a past config change, not whether today's tasks need a restart.
        // Keep that caveat in connection details; show a conditional notice after a choice made here.
        el('restart').hidden = !state.restart_required || !connectionChangedHere;
        el('restart').textContent = state.restart_required && connectionChangedHere
            ? 'Connection preference saved. Restart Codex only if an already-open task has not picked up this change. Tasks already using the selected connection can continue.' : '';
        if (state.mode === 'opencodex') {
            el('status').textContent = changing ? 'Applying request compression setting...'
                : state.effective_enabled ? 'OpenCodex compression enabled'
                : state.enabled ? 'OpenCodex compression waiting for readiness' : 'OpenCodex compression paused';
            el('enable').disabled = changing || !state.installed || !state.validated || state.enabled;
            el('pause').disabled = changing || !state.enabled;
            el('saved').textContent = available ? number(selected.saved_tokens) : 'Waiting for first measurement';
            el('scope').textContent = 'Estimated tokens removed from OpenCodex tool results · ' + label + ' · all tasks. Measured since live metering was enabled.';
            if (available && !recent.complete) el('scope').textContent += ' Partial record coverage; this total may be incomplete.';
            el('window-detail').textContent = available ? number(selected.requests) + ' transform replies measured in this window' : 'No live OpenCodex measurements recorded yet.';
            el('coverage').textContent = 'Includes cached replies, zero-savings replies and diagnostic checks. These estimates measure worker responses, not confirmed provider usage or quota savings.'
                + (recent && !recent.complete ? ' Partial ledger coverage: totals include only available valid records.' : '');
            el('active-rate').textContent = percent(selected.reduction_pct);
            el('whole-rate').textContent = 'Not reported';
            el('backend-scope').textContent = 'Rates use the last 24 hours and all tool text submitted to the worker, including replies with no savings. Complete-request token totals are not measured.';
            el('rate-note').textContent = 'Only eligible tool-result text is submitted for compression. Protected conversation content is preserved. Savings before live metering was enabled cannot be reconstructed.';
            el('diagnostics').textContent = 'Worker outcomes below count newly computed batches since worker start; cached replies also contribute to the measured savings above.';
            el('timing').hidden = true;
            var outcomes = state.transform_outcomes || {};
            el('counts').textContent = 'Tool-result batches since worker start: ' + number(outcomes.compressed)
                + ' compressed; ' + number(outcomes.unchanged) + ' unchanged; ' + number(outcomes.bypassed)
                + ' bypassed; ' + number(outcomes.error) + ' errors. Includes diagnostic checks; these are not model-request counts.';
            el('routing').textContent = 'Connection mode: OpenCodex.';
            el('backend').textContent = state.ready ? 'Local transform worker is ready.' : 'Local transform worker is not ready.';
            el('recorded').textContent = savings.last_recorded_at
                ? 'Last measured OpenCodex reply: ' + new Date(savings.last_recorded_at).toLocaleString()
                : 'Waiting for the first measured OpenCodex reply.';
            el('restart').hidden = !state.restart_required;
            el('restart').textContent = state.restart_required ? 'OpenCodex must reload its integration settings before compression can become active.' : '';
        }
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
            if (response.ok) { state = data; connectionChangedHere = true; }
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
