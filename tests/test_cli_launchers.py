"""Real Windows launcher boundary: literal argv, cwd, stdin and exit status."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name != 'nt', reason='Windows native launcher')
@pytest.mark.parametrize('name,component', [('ast-grep', 'ast_grep'), ('playwright-cli', 'playwright_cli')])
def test_literal_arguments_through_native_launcher(tmp_path, name, component):
    root = tmp_path / 'Bundle space ภาษาไทย'
    binary = root / 'bin'
    python = root / 'headroom/.venv/Scripts/python.exe'
    binary.mkdir(parents=True)
    python.parent.mkdir(parents=True)
    shutil.copy2(ROOT / 'bin' / (name + '.exe'), binary)
    source = root / 'Fixture.cs'
    source.write_text('''using System; using System.IO; using System.Web.Script.Serialization;
class Fixture { static int Main(string[] args) {
Console.OutputEncoding = new System.Text.UTF8Encoding(false);
Console.Write(new JavaScriptSerializer().Serialize(new {args=args, cwd=Environment.CurrentDirectory, input=Console.In.ReadToEnd()}));
return 37; } }''')
    compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler), '/nologo', '/reference:System.Web.Extensions.dll', '/out:' + str(python), str(source)], check=True, capture_output=True)
    args = ['run', '-p', '$A.foo("quoted & value")', '', 'trailing\\', '|', '>output.txt']
    result = subprocess.run([str(binary / (name + '.exe')), *args], cwd=root, input='literal stdin\n',
                            capture_output=True, text=True, encoding='utf-8', timeout=15)
    assert result.returncode == 37
    data = json.loads(result.stdout)
    assert data['args'] == [str(root / 'cli_tools.py'), component, *args]
    assert data['cwd'] == str(root)
    assert data['input'] == 'literal stdin' + os.linesep
    assert not (root / 'output.txt').exists()
