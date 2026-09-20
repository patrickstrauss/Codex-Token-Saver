"""Launch Codex directly; optional Headroom settings exist only in this process."""
import os
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parent


def ensure_headroom():
    from service_control import ServiceController
    result = ServiceController(ROOT).ensure('headroom')
    return result['ready']


def experimental_skip_reason(arguments):
    """Do not redirect explicit/custom routes or guess through invalid config."""
    for name in ('OPENAI_BASE_URL', 'OPENAI_API_BASE', 'AZURE_OPENAI_ENDPOINT', 'CODEX_OSS_BASE_URL'):
        if os.environ.get(name):
            return f'{name} already selects an endpoint'
    selected_profile = None
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == '--':
            break
        if argument == '--oss' or argument == '--local-provider' or argument.startswith('--local-provider='):
            return 'the command selects a local provider'
        override = None
        if argument in ('-c', '--config', '-p', '--profile'):
            if index + 1 == len(arguments):
                return 'a config or profile argument is incomplete'
            index += 1
            if argument in ('-p', '--profile'):
                selected_profile = arguments[index]
            else:
                override = arguments[index]
        elif argument.startswith('--config='):
            override = argument.partition('=')[2]
        elif argument.startswith('-c') and len(argument) > 2:
            override = argument[2:].removeprefix('=')
        elif argument.startswith('--profile='):
            selected_profile = argument.partition('=')[2]
        elif argument.startswith('-p') and len(argument) > 2:
            selected_profile = argument[2:].removeprefix('=')
        if override is not None:
            key, separator, _ = override.partition('=')
            try:
                parsed_key = tomllib.loads(key.strip() + '=0') if separator else {}
            except tomllib.TOMLDecodeError:
                return 'a config override cannot be checked safely'
            if not parsed_key or set(parsed_key) & {'model_provider', 'model_providers', 'openai_base_url', 'profile', 'profiles'}:
                return 'the command explicitly sets a provider, endpoint, or profile'
        index += 1
    config_file = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'config.toml'
    try:
        config = tomllib.loads(config_file.read_text(encoding='utf-8-sig')) if config_file.exists() else {}
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return 'Codex config could not be read safely'
    selected_profile = selected_profile if selected_profile is not None else config.get('profile')
    profile = {}
    if selected_profile is not None:
        profiles = config.get('profiles', {})
        profile = profiles.get(selected_profile) if isinstance(profiles, dict) and isinstance(selected_profile, str) else None
        if not isinstance(profile, dict):
            return 'the selected profile could not be resolved'
    provider = profile.get('model_provider', config.get('model_provider', 'openai'))
    if provider != 'openai':
        return 'Codex uses a custom provider'
    if 'openai_base_url' in config or 'openai_base_url' in profile:
        return 'Codex already has an explicit endpoint'
    for settings in (config, profile):
        providers = settings.get('model_providers', {})
        if not isinstance(providers, dict) or 'openai' in providers:
            return 'the built-in OpenAI provider has custom settings'
    return None


def prepare_arguments(arguments, experimental=False):
    if not experimental:
        return list(arguments)
    reason = experimental_skip_reason(arguments)
    if reason:
        print(f'Headroom skipped: {reason}. Launching Codex directly.', file=sys.stderr)
        return list(arguments)
    try:
        ready = ensure_headroom()
    except Exception as exc:
        print(f'Headroom could not start ({exc}). Launching Codex directly.', file=sys.stderr)
        return list(arguments)
    if not ready:
        print('Headroom is unavailable. Launching Codex directly.', file=sys.stderr)
        return list(arguments)
    print('Experimental Headroom session. Codex desktop settings are unchanged.', file=sys.stderr)
    # Keep the built-in provider's OAuth/API-key behavior and model selection.
    return ['-c', 'openai_base_url="http://127.0.0.1:8787/v1"'] + list(arguments)


def find_codex():
    local_app_data = os.environ.get('LOCALAPPDATA')
    if not local_app_data:
        raise RuntimeError('LOCALAPPDATA is unavailable; Codex desktop executable cannot be located.')
    local = Path(local_app_data)
    root = local / 'OpenAI' / 'Codex' / 'bin'
    package_roots = list((local / 'Packages').glob('OpenAI.Codex_*/LocalCache/Local/OpenAI/Codex/bin'))
    # Current desktop runtimes are versioned. Direct binaries can be old stubs.
    groups = [list(root.glob('*/codex.exe')),
              [path for package in package_roots for path in package.glob('*/codex.exe')],
              [root / 'codex.exe'], [package / 'codex.exe' for package in package_roots]]
    for candidates in groups:
        available = []
        for path in candidates:
            try:
                if path.is_file():
                    available.append((path.stat().st_mtime, path))
            except OSError:
                continue  # A desktop update may remove an older runtime mid-scan.
        if available:
            return max(available, key=lambda item: item[0])[1]
    raise RuntimeError('Codex desktop executable not found. Open or reinstall Codex desktop.')


def run_cli(executable, arguments):
    environment = os.environ.copy()
    environment['PATH'] = str(ROOT / 'bin') + os.pathsep + environment.get('PATH', '')
    # No shell, no argument rewriting, and no retries that could repeat user actions.
    return subprocess.call([str(executable)] + list(arguments), env=environment)


def main():
    arguments = sys.argv[1:]
    experimental = bool(arguments and arguments[0] == '--experimental-headroom')
    if experimental:
        arguments.pop(0)
    if arguments and arguments[0] == '--':
        arguments.pop(0)
    return run_cli(find_codex(), prepare_arguments(arguments, experimental))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError) as exc:
        print(f'Codex launcher: {exc}', file=sys.stderr)
        sys.exit(1)
