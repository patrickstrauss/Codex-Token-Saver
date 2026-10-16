"""Run an existing stdio server in-process for an explicitly selected MCP client."""
import argparse
import os
from pathlib import Path
import runpy
import sys


def launch(client, component, root=None):
    from harness_clients import CLIENTS, SCRIPTS
    if client not in CLIENTS or component not in SCRIPTS:
        raise ValueError('Unknown client or component.')
    root = Path(root or Path(__file__).resolve().parent).resolve()
    # Foreign session IDs must never be looked up in Codex's conversation database.
    os.environ.pop('CODEX_THREAD_ID', None)
    os.environ['CTS_CLIENT'] = client
    os.environ['HEADROOM_WORKSPACE_DIR'] = str(root / 'headroom/desktop-state')
    os.chdir(root)
    sys.argv = [str(root / SCRIPTS[component][1])]
    runpy.run_path(sys.argv[0], run_name='__main__')


if __name__ == '__main__':
    from harness_clients import CLIENTS, SCRIPTS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', required=True, choices=CLIENTS)
    parser.add_argument('--component', required=True, choices=SCRIPTS)
    args = parser.parse_args()
    launch(args.client, args.component)
