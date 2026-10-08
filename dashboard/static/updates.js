/* Local status polling never checks release servers or starts an update. */
(function () {
    'use strict';
    var panel = document.getElementById('library-updates');
    if (!panel) return;
    var csrf = document.querySelector('meta[name="bundle-update-token"]').content;
    var state = {busy: false, components: []};
    var actionPending = false, readPending = false, sequence = 0, requestError = '';
    var components = ['headroom', 'rtk', 'serena', 'laya'];
    var names = {headroom: 'Headroom', rtk: 'RTK', serena: 'Serena', laya: 'Laya'};
    function el(id) { return document.getElementById(id); }
    function render() {
        var busy = actionPending || state.busy;
        el('updates-check').disabled = busy;
        el('updates-progress').hidden = !busy;
        el('updates-summary').textContent = busy ? 'Update in progress' : 'Bundle libraries';
        el('updates-message').textContent = state.message || 'Check manually when you want newer releases.';
        el('updates-stage').textContent = busy && state.stage ? state.stage.replace(/_/g, ' ') : '';
        el('updates-error').textContent = state.error || requestError;
        el('updates-error').hidden = !el('updates-error').textContent;
        el('updates-checked').textContent = state.last_checked ? 'Last checked: ' + new Date(state.last_checked).toLocaleString() : 'No release check yet';
        el('updates-log').textContent = state.log === 'updates/last-operation.log'
            ? 'Operation log: updates/last-operation.log inside your Codex Token Saver folder.' : '';
        var restart = false;
        components.forEach(function (id) {
            var component = (state.components || []).find(function (item) { return item.id === id; }) || {};
            el('update-' + id + '-current').textContent = component.current || 'Unavailable';
            el('update-' + id + '-latest').textContent = component.latest || 'Not checked';
            var refresh = component.refresh_available && !component.update_available;
            el('update-' + id + '-install').disabled = busy || !(component.update_available || refresh);
            el('update-' + id + '-install').textContent = refresh ? 'Refresh dependencies' : 'Update ' + names[id];
            el('update-' + id + '-rollback').disabled = busy || !component.rollback_available;
            el('update-' + id + '-error').textContent = component.error || '';
            restart = restart || component.restart_required;
        });
        el('updates-restart').hidden = !restart;
        el('updates-restart').textContent = restart
            ? 'Restart Codex to load updated file tools or Serena already running. New command and Laya workers use the selected runtime.' : '';
    }
    async function loadStatus() {
        if (readPending || actionPending) return;
        readPending = true;
        var requestId = ++sequence;
        try {
            var response = await fetch('/api/updates', {cache: 'no-store', credentials: 'same-origin'});
            var data = await response.json();
            if (requestId !== sequence) return;
            if (!response.ok) throw new Error(data.error || 'Update status is unavailable.');
            state = data;
        } catch (error) {
            if (requestId === sequence) requestError = 'Update status is unavailable. Try reopening this panel.';
        } finally {
            readPending = false;
            render();
        }
    }
    async function run(action, component) {
        if (actionPending || state.busy) return;
        actionPending = true;
        ++sequence; // An older GET must not overwrite this operation's status.
        requestError = '';
        render();
        var payload = {action: action};
        if (component) payload.component = component;
        try {
            var response = await fetch('/api/updates', {
                method: 'POST', credentials: 'same-origin', cache: 'no-store',
                headers: {'Content-Type': 'application/json', 'X-Codex-Update-Token': csrf},
                body: JSON.stringify(payload)
            });
            var data = await response.json();
            if (!response.ok) requestError = data.error || 'The update request failed. Check the status before trying again.';
            else state = data;
        } catch (error) {
            requestError = 'The response was interrupted. Check the status before trying again.';
        } finally {
            actionPending = false;
            render();
        }
    }
    el('updates-check').addEventListener('click', function () { run('check'); });
    components.forEach(function (id) {
        el('update-' + id + '-install').addEventListener('click', function () { run('install', id); });
        el('update-' + id + '-rollback').addEventListener('click', function () { run('rollback', id); });
    });
    panel.addEventListener('toggle', function () { if (panel.open) loadStatus(); });
    setInterval(function () { if (panel.open || state.busy) return loadStatus(); }, 2000);
    render();
})();
