"""Record dependency versions without paths, environment values or user data."""
import argparse
import json
from pathlib import Path
import subprocess


def inventory(root):
    components = {}
    code = '''import importlib.metadata as m, json, platform
print(json.dumps({"python":platform.python_version(),"packages":sorted([
{"name":d.metadata["Name"],"version":d.version,
 "license":(d.metadata.get("License-Expression") or d.metadata.get("License") or "Not reported")[:120]}
 for d in m.distributions()],key=lambda d:d["name"].lower())}))'''
    for name in ('headroom', 'dashboard', 'serena', 'laya'):
        python = root / name / '.venv/Scripts/python.exe'
        if python.exists():
            result = subprocess.run([str(python), '-I', '-c', code], capture_output=True,
                                    text=True, encoding='utf-8', check=True, timeout=30)
            components[name] = json.loads(result.stdout)
    return {'schema_version': 1, 'python_runtimes': components,
            'binary_pins': json.loads((root / 'packaging/dependencies.json').read_bytes()),
            'npm_lock': json.loads((root / 'packaging/package-lock.json').read_bytes()),
            'model_pins': json.loads((root / 'packaging/laya-model.json').read_bytes()),
            'scope': 'Pinned clean install; license metadata is informational, not a compliance certificate.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory(args.root), indent=2) + '\n', encoding='utf-8')
