/* Workspace navigation and appearance only. No models, mutations or extra polling. */
(function () {
    'use strict';
    var links = Array.from(document.querySelectorAll('[data-view-link]'));
    var views = Array.from(document.querySelectorAll('[data-workspace-view]'));
    var titles = {
        overview: ['Overview', 'Local coding tools and measurements across your connected clients.'],
        toolkit: ['Your toolkit', 'Choose your tools. See what is ready and what needs attention.'],
        activity: ['Activity', 'Explore recorded operations and automatic hook coverage.'],
        updates: ['Library updates', 'Keep your bundle current, with compatibility checks and rollback.'],
        diagnostics: ['Diagnostics', 'Inspect detailed measurements and the live savings feed.']
    };
    function showView(focus) {
        var key = location.hash.slice(1);
        if (!Object.prototype.hasOwnProperty.call(titles, key)) key = 'overview';
        views.forEach(function (view) { view.hidden = view.dataset.workspaceView !== key; });
        links.forEach(function (link) {
            if (link.dataset.viewLink === key) link.setAttribute('aria-current', 'page');
            else link.removeAttribute('aria-current');
        });
        var heading = document.getElementById('page-title');
        heading.textContent = titles[key][0];
        document.getElementById('page-description').textContent = titles[key][1];
        var manageLink = document.getElementById('manage-toolkit');
        if (manageLink) manageLink.hidden = key !== 'overview';
        // Only poll idle update status while its view is open. Active jobs keep polling.
        document.getElementById('library-updates').open = key === 'updates';
        document.title = titles[key][0] + ' · Codex Token Saver';
        if (focus) { heading.focus({preventScroll: true}); window.scrollTo(0, 0); }
    }
    window.addEventListener('hashchange', function () {
        // Leave in-page anchors (including the skip link) to the browser.
        if (Object.prototype.hasOwnProperty.call(titles, location.hash.slice(1))) showView(true);
    });
    showView(false);

    var themeButton = document.getElementById('theme-toggle');
    function applyTheme(theme) {
        document.documentElement.dataset.theme = theme;
        themeButton.setAttribute('aria-label', 'Switch to ' + (theme === 'light' ? 'dark' : 'light') + ' theme');
        themeButton.setAttribute('aria-pressed', String(theme === 'light'));
    }
    var saved = null;
    try { saved = localStorage.getItem('cts-theme'); } catch (_) { /* Storage may be blocked. */ }
    applyTheme(saved === 'light' ? 'light' : 'dark');
    themeButton.addEventListener('click', function () {
        var theme = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
        applyTheme(theme);
        try { localStorage.setItem('cts-theme', theme); } catch (_) { /* Appearance still works. */ }
    });
    document.getElementById('refresh-dashboard').addEventListener('click', function () { location.reload(); });

    var pulse = document.getElementById('health-pulse');
    function health() {
        var label = document.getElementById('connection-label');
        var state = pulse.classList.contains('health-error') ? 'error'
            : pulse.classList.contains('health-stale') ? 'stale'
            : pulse.dataset.pending ? 'pending' : 'ok';
        var text = {error: 'Needs attention', stale: 'Check connection', pending: 'Connecting', ok: 'Connected'}[state];
        if (label.textContent !== text) label.textContent = text;
        label.parentElement.dataset.health = state;
        label.parentElement.title = pulse.title;
    }
    new MutationObserver(health).observe(pulse, {attributes: true, attributeFilter: ['class', 'title', 'data-pending']});
    health();
})();
