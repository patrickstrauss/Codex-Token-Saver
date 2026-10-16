/* Setup exports only. Registration is reviewed and applied in the native CLI. */
(function () {
    'use strict';
    var panel = document.getElementById('coding-clients');
    if (!panel) return;
    var select = document.getElementById('client-choice');
    var status = document.getElementById('client-status');
    var output = document.getElementById('client-config');
    var command = document.getElementById('client-command');
    var button = document.getElementById('client-preview');
    var token = document.querySelector('meta[name="bundle-update-token"]').content;
    var paths = {'claude-code':'User: ~/.claude.json · Project: .mcp.json',
        'gemini-cli':'User: ~/.gemini/settings.json · Project: .gemini/settings.json',
        cursor:'User: ~/.cursor/mcp.json · Project: .cursor/mcp.json',
        opencode:'User: ~/.config/opencode/opencode.json · Project: opencode.json or opencode.jsonc',
        vscode:'Use MCP: Open User Configuration for the active profile, or workspace .vscode/mcp.json.',
        cline:'CLI: ~/.cline/data/settings/cline_mcp_settings.json. For the IDE use Configure MCP Servers, then supply that exact file with -Config.',
        kilo:'User: ~/.config/kilo/kilo.jsonc · Project: .kilo/kilo.jsonc (existing root kilo.json/jsonc also supported).',
        'windsurf-cascade':'Legacy Cascade: select the MCP config file through its UI and supply -Config. The current Devin Local agent uses a different configuration.',
        generic:'Merge mcpServers into your client’s documented stdio MCP configuration.'};
    function choose() {
        output.textContent = ''; command.textContent = '';
        document.getElementById('client-path').textContent = paths[select.value] || '';
    }
    select.addEventListener('change', choose);
    fetch('/api/clients', {cache:'no-store'}).then(function (response) {
        if (!response.ok) throw new Error();
        return response.json();
    }).then(function (data) {
        data.clients.forEach(function (client) {
            var option = document.createElement('option'); option.value = client.id;
            option.textContent = client.label; select.append(option);
        });
        status.textContent = (data.codex_integration ? 'Codex setup retained. ' : 'Standalone installation. ') +
            data.registrations.length + ' additional client configuration(s) recorded. Client loading is unverified.';
        button.disabled = false; choose();
    }).catch(function () { status.textContent = 'Client setup is unavailable. Refresh or use Connect-Harness.ps1.'; });
    button.addEventListener('click', function () {
        button.disabled = true;
        fetch('/api/clients/export', {method:'POST', headers:{'Content-Type':'application/json',
            'X-Codex-Update-Token':token}, body:JSON.stringify({client:select.value})}).then(function (response) {
            if (!response.ok) throw new Error();
            return response.json();
        }).then(function (data) {
            output.textContent = JSON.stringify(data.config, null, 2);
            var suffix = select.value === 'vscode' ? ' -Scope project -Project \'C:\\path\\to\\project\'' :
                (select.value === 'generic' || select.value === 'windsurf-cascade') ? ' -Config \'C:\\path\\to\\mcp.json\'' : '';
            command.textContent = '& \'' + data.script.replace(/'/g, "''") + '\' -Action connect -Client ' + select.value + suffix;
            status.textContent = 'Preview only. Run the command in PowerShell to inspect its plan; append -Apply to register. Or merge the JSON manually. Reload the client and approve its MCP trust prompt.';
        }).catch(function () { status.textContent = 'Export failed. Check the installed runtime and refresh this page.'; })
            .finally(function () { button.disabled = false; });
    });
}());
