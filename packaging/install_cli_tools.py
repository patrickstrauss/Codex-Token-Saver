"""Install pinned Windows CLI runtimes locally; never alter global Node or PATH."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile


def install(root):
    root = Path(root).resolve()
    sys.path.insert(0, str(root))
    from cli_tools import runtime_paths, command, runtime_status
    node, packages, digest = runtime_paths(root)
    pins = json.loads((root / 'packaging/dependencies.json').read_bytes())
    expected = json.loads((root / 'packaging/package.json').read_bytes())['dependencies']
    lock = json.loads((root / 'packaging/package-lock.json').read_bytes())
    for key, entry in lock['packages'].items():
        if key and (not entry.get('resolved', '').startswith('https://registry.npmjs.org/')
                    or not entry.get('integrity', '').startswith('sha512-')):
            raise ValueError('Every npm dependency must have a registry URL and SHA-512 integrity.')
    downloads = root / 'downloads/agent-clis'
    downloads.mkdir(parents=True, exist_ok=True)
    if not node.is_dir():
        pin = pins['node']
        archive = downloads / (node.name + '.zip')
        if not archive.exists():
            print('Downloading pinned Node ' + pin['version'], flush=True)
            partial = archive.with_suffix('.partial')
            with urllib.request.urlopen(pin['url'], timeout=60) as response, partial.open('wb') as stream:
                shutil.copyfileobj(response, stream)
            if hashlib.sha256(partial.read_bytes()).hexdigest() != pin['sha256']:
                raise ValueError('Node archive checksum mismatch.')
            partial.replace(archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != pin['sha256']:
            raise ValueError('Cached Node archive checksum mismatch.')
        stage = Path(tempfile.mkdtemp(prefix='node-stage-', dir=downloads)).resolve()
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                if not (stage / member.filename).resolve().is_relative_to(stage):
                    raise ValueError('Unsafe Node archive member.')
            bundle.extractall(stage)
        node.parent.mkdir(parents=True, exist_ok=True)
        source = stage / node.name
        # Both absolute paths are confined to this installation before moving.
        if not source.resolve().is_relative_to(downloads.resolve()) or not node.resolve().is_relative_to(root / 'tools'):
            raise ValueError('Runtime path escaped the bundle.')
        source.rename(node)
    actual_node = subprocess.check_output([str(node / 'node.exe'), '--version'], text=True).strip()
    if actual_node != 'v' + pins['node']['version']:
        raise ValueError('Unexpected installed Node version; existing runtime preserved.')
    if not runtime_status(root)['available']:
        if packages.exists() and any(not (packages / name).is_file() or
                                     (packages / name).read_bytes() != (root / 'packaging' / name).read_bytes()
                                     for name in ('package.json', 'package-lock.json')):
            raise ValueError('An unfamiliar CLI runtime exists at ' + str(packages) + '; preserved for review.')
        packages.mkdir(parents=True, exist_ok=True)
        for filename in ('package.json', 'package-lock.json'):
            shutil.copy2(root / 'packaging' / filename, packages / filename)
        empty_config = downloads / 'empty.npmrc'
        empty_config.write_text('', encoding='utf-8')
        global_config = downloads / 'empty-global.npmrc'
        global_config.write_text('', encoding='utf-8')
        environment = {key: value for key, value in os.environ.items() if not key.lower().startswith('npm_config_')}
        environment['PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD'] = '1'
        environment['PATH'] = str(node) + os.pathsep + environment.get('PATH', '')
        print('Installing integrity-locked Playwright CLI and ast-grep (no npm lifecycle scripts).', flush=True)
        subprocess.run([str(node / 'node.exe'), str(node / 'node_modules/npm/bin/npm-cli.js'),
                        'ci', '--ignore-scripts', '--include=optional', '--no-audit', '--no-fund',
                        '--registry=https://registry.npmjs.org', '--cache=' + str(downloads / 'npm-cache'),
                        '--userconfig=' + str(empty_config), '--globalconfig=' + str(global_config)],
                       cwd=packages, env=environment, check=True, timeout=600)
    for name, package in (('playwright_cli', '@playwright/cli'), ('ast_grep', '@ast-grep/cli')):
        version = subprocess.check_output([*command(root, name), '--version'], text=True, timeout=30).strip()
        if expected[package] not in version:
            raise ValueError('Unexpected installed version: ' + name + ' ' + version)
        print(name + ': ' + version, flush=True)
    # Real AST match: ignore the identical text in a string and in a comment.
    with tempfile.TemporaryDirectory(prefix='cli-check-') as temp:
        fixture = Path(temp) / 'example.js'
        fixture.write_text('console.log(answer);\n// console.log(comment);\nconst text="console.log(string)";\n')
        output = subprocess.check_output([*command(root, 'ast_grep'), 'run', '--lang', 'javascript',
                                         '--pattern', 'console.log($A)', '--json=compact', str(fixture)], text=True, timeout=30)
        matches = json.loads(output)
        if len(matches) != 1 or matches[0]['text'] != 'console.log(answer)':
            raise ValueError('Structural search qualification failed.')
    (packages / 'ready.json').write_text(json.dumps({'lock_sha256': digest, 'versions': expected}) + '\n', encoding='utf-8')
    print('CLI runtime validated; component choices preserved.', flush=True)


if __name__ == '__main__':
    install(Path(sys.argv[1]).resolve())
