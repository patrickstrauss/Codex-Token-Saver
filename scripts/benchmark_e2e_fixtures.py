"""Frozen, synthetic coding workloads and independent quality checks."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def cases():
    logs = ''.join(
        'ERROR component=storage code=E_QUEUE_FULL remedy=queue_capacity:512 job=failed\n'
        if row == 281 else f'INFO worker={row % 8} job={row} health=OK latency=10ms\n'
        for row in range(600))
    modules = {
        'shop/__init__.py': '',
        'shop/pricing.py': 'def compute_total(prices):\n    return sum(prices) * 1.07\n',
        'shop/validation.py': 'def validate_prices(prices):\n    return all(price >= 0 for price in prices)\n',
        'shop/service.py': 'from .pricing import compute_total as invoice\nfrom .validation import validate_prices\n\ndef checkout(prices):\n    if not validate_prices(prices):\n        raise ValueError("negative price")\n    return invoice(prices)\n',
        'shop/legacy.py': 'def compute_total(prices):\n    """Unused legacy implementation."""\n    return sum(prices)\n',
    }
    for i in range(6):
        modules[f'shop/report_{i}.py'] = f'def report_{i}(value):\n    return str(value)\n'
    js = {
        'routes/public.js': "registry.register_route('catalog', () => catalog());\nregistry.register_route(\n  'health',\n  async () => health()\n);\n",
        'routes/private.js': "function install() {\n registry.register_route('invoice', (request) => invoice(request));\n if (enabled) registry.register_route('refund', refund);\n}\n",
        'routes/decoys.js': '// registry.register_route("fake-comment", handler);\nconst example = "registry.register_route(\'fake-string\', handler)";\nother.register_route("wrong-receiver", handler);\n',
        'routes/archive.js': '/* registry.register_route("archived", handler); */\nconst disabled = true;\n',
    }
    for i in range(6):
        js[f'routes/utility_{i}.js'] = f'export function helper_{i}(value) {{ return value; }}\n'
    retry = ('def retry_delay(attempt, base=1, cap=30):\n'
             '    """Return the delay for a 1-based retry attempt."""\n'
             '    return min(cap, base * (2 ** attempt))\n')
    public_tests = '''import unittest
from retries import retry_delay
class RetryTests(unittest.TestCase):
    def test_first(self): self.assertEqual(retry_delay(1), 1)
    def test_backoff(self): self.assertEqual(retry_delay(3, base=2), 8)
    def test_cap(self): self.assertEqual(retry_delay(8, cap=10), 10)
if __name__ == '__main__': unittest.main()
'''
    return [
        {'id': 'log-diagnosis', 'files': {'logs/worker.log': logs, 'README.md': '# Worker log fixture\n'},
         'prompt': 'Diagnose the failed job in logs/worker.log. Report its component, error code and the remedy exactly as recorded.',
         'expected': {'component': 'storage', 'code': 'E_QUEUE_FULL', 'remedy': 'queue_capacity:512'}},
        {'id': 'symbol-tracing', 'files': modules,
         'prompt': 'Trace shop.service.checkout: identify the source function actually used for invoice computation (not the unused legacy name), its source file, and the validation function called before it.',
         'expected': {'implementation': 'compute_total', 'source': 'shop/pricing.py', 'validation': 'validate_prices'}},
        {'id': 'structural-audit', 'files': js,
         'prompt': 'Inspect routes/. List all first string arguments of actual JavaScript calls to registry.register_route, sorted alphabetically and joined with commas. Exclude comments, string examples and calls on other receivers. Return the list in routes.',
         'expected': {'routes': 'catalog,health,invoice,refund'}},
        {'id': 'tested-code-fix', 'files': {'retries.py': retry, 'test_retries.py': public_tests},
         'prompt': 'Fix only retries.py. retry_delay uses 1-based attempts: return min(cap, base * 2**(attempt-1)). attempt must be an integer >=1, excluding bool. base and cap must be finite nonnegative int/float values, excluding bool. Raise ValueError for invalid inputs. Keep the signature/defaults, pass test_retries.py and verify edge cases. Do not alter the tests.',
         'expected': None, 'editable': ['retries.py']},
        {'id': 'patch-review', 'files': {'settings.ini': 'timeout_seconds=30\nretry_limit=3\n',
                                        'README.md': '# Service configuration\n'},
         'mutations': {'settings.ini': 'timeout_seconds=60\nretry_limit=0\n',
                       'README.md': '# Service configuration\n\nUpdated operations notes.\n'},
         'prompt': 'Review the uncommitted Git patch. Report old_timeout, new_timeout, old_retries and new_retries as strings, and flag whether automatic retries were disabled (yes/no). Inspect the actual diff, not only file statistics.',
         'expected': {'old_timeout': '30', 'new_timeout': '60', 'old_retries': '3', 'new_retries': '0', 'retries_disabled': 'yes'}},
    ]


def schema(case):
    keys = case['expected'] or {'summary': ''}
    return {'type': 'object', 'properties': {key: {'type': 'string'} for key in keys},
            'required': list(keys), 'additionalProperties': False}


def digest_files(files):
    return {name: hashlib.sha256(text.encode()).hexdigest() for name, text in sorted(files.items())}


def manifest(seed):
    return {'schema_version': 1, 'seed': seed, 'model_calls': 0,
            'scope': 'Five paired tool-using coding tasks; explicit bundle tools, native provider',
            'cases': [{'id': case['id'], 'prompt': case['prompt'],
                       'files_sha256': digest_files(case['files']),
                       'mutations_sha256': digest_files(case.get('mutations', {})),
                       'expected': case['expected'], 'editable': case.get('editable', []),
                       'schema': schema(case)} for case in cases()]}


def prepare(case, workspace, git, env):
    workspace.mkdir(parents=True)
    for name, text in case['files'].items():
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')
    def run(*args):
        subprocess.run([git, '-c', 'core.autocrlf=false', '-c', 'commit.gpgsign=false',
                        '-c', 'core.hooksPath=' + str(workspace / '.git/no-hooks'), *args],
                       cwd=workspace, env=env, check=True, capture_output=True, timeout=20)
    run('init', '--quiet')
    run('add', '.')
    run('-c', 'user.name=Benchmark', '-c', 'user.email=benchmark@example.invalid',
        'commit', '--quiet', '-m', 'Synthetic baseline')
    for name, text in case.get('mutations', {}).items():
        (workspace / name).write_text(text, encoding='utf-8', newline='\n')


# Kept outside the model workspace; the model receives requirements, not this oracle.
ORACLE = '''import importlib.util, math, sys
spec=importlib.util.spec_from_file_location('candidate',sys.argv[1])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
f=module.retry_delay
assert f(1)==1 and f(3,base=2)==8 and f(8,cap=10)==10
assert f(1,base=0)==0 and f(3,base=0.25,cap=0.7)==0.7 and f(2,cap=0)==0
for args in [(0,),(-1,),(True,),(1.5,),('1',),(1,-1),(1,True),(1,float('nan')),(1,float('inf')),(1,1,-1),(1,1,False),(1,1,float('nan')),(1,1,float('inf'))]:
    try: f(*args)
    except ValueError: pass
    else: raise AssertionError('invalid input accepted')
assert f(100000,base=0,cap=30)==0
print('ORACLE_OK')
'''


def grade(case, workspace, answer):
    altered = []
    for name, original in (case['files'] | case.get('mutations', {})).items():
        if name in case.get('editable', []):
            continue
        try:
            same = (workspace / name).read_text(encoding='utf-8') == original
        except OSError:
            same = False
        if not same:
            altered.append(name)
    quality = {'immutable_files_preserved': not altered, 'altered_fixture_files': altered}
    if case['expected'] is not None:
        quality['answer_correct'] = answer == case['expected']
    else:
        try:
            test = subprocess.run([sys.executable, '-I', '-c', ORACLE, str(workspace / 'retries.py')],
                                  cwd=workspace, capture_output=True, timeout=10)
            quality['hidden_tests_passed'] = test.returncode == 0 and b'ORACLE_OK' in test.stdout
        except (OSError, subprocess.TimeoutExpired):
            quality['hidden_tests_passed'] = False
        quality['answer_correct'] = isinstance(answer, dict) and isinstance(answer.get('summary'), str)
    quality['passed'] = all(value for key, value in quality.items() if key != 'altered_fixture_files')
    return quality
