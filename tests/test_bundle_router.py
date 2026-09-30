import json
from pathlib import Path
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bundle_router as router
from bundle_preferences import set_preference, load_preferences


@pytest.fixture
def fixture(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'code.js').write_text('console.log(answer);')
    root = tmp_path / 'bundle'
    set_preference(root, 'laya_router', True)
    set_preference(root, 'ast_grep', True)
    request = {'intent': 'Find this code pattern', 'project': str(project), 'path': 'code.js',
               'pattern': 'console.log($A)', 'language': 'javascript'}
    return root, project, request


def decision(route='ast_search', **kwargs):
    return dict(route=route, confidence=.9, delivery='compact', truncated=False, elapsed_ms=12, **kwargs)


def test_laya_runs_before_execution_and_records_no_prompt(fixture):
    root, project, request = fixture
    events = []
    def predict(*args):
        events.append('laya')
        assert 'ast_search' in args[2]
        return decision()
    def execute(*args):
        events.append('execute')
        return 'result', ['laya', 'ast_grep', 'headroom_local']
    with patch.object(router, 'execute', side_effect=execute):
        value = router.query(root, request, predict)
    assert events == ['laya', 'execute']
    assert value['sequence'] == ['laya', 'ast_grep', 'headroom_local']
    stored = (root / 'data/router/activity.json').read_text()
    assert request['intent'] not in stored and request['pattern'] not in stored


@pytest.mark.parametrize('bad', [
    {'route': 'powershell'}, {'confidence': float('nan')}, {'confidence': .79},
    {'truncated': True}, {'delivery': 'run-shell'}, {'route': 'clarify'}])
def test_bad_or_uncertain_decisions_never_execute(fixture, bad):
    root, _, request = fixture
    value = decision() | bad
    with patch.object(router, 'execute') as execute:
        with pytest.raises(ValueError):
            router.query(root, request, lambda *args: value)
        execute.assert_not_called()


def test_off_blocks_even_a_loaded_tool(fixture):
    root, _, request = fixture
    set_preference(root, 'laya_router', False)
    predictor = Mock()
    with pytest.raises(ValueError, match='Off'):
        router.query(root, request, predictor)
    predictor.assert_not_called()


def test_toggle_change_after_classification_blocks_backend(fixture):
    root, _, request = fixture
    def predict(*args):
        set_preference(root, 'ast_grep', False)
        return decision()
    with patch.object(router, 'run_command') as run:
        with pytest.raises(RuntimeError, match='disabled'):
            router.query(root, request, predict)
        run.assert_not_called()


def test_paths_cannot_escape_project_before_laya(fixture):
    root, project, request = fixture
    (project.parent / 'outside.txt').write_text('outside')
    predictor = Mock()
    with pytest.raises(ValueError, match='within'):
        router.query(root, request | {'path': '../outside.txt'}, predictor)
    predictor.assert_not_called()


def test_missing_parameters_are_not_invented(fixture):
    root, project, _ = fixture
    request = {'intent': 'Navigate somewhere', 'project': str(project)}
    assert router.eligible_recipes(root, request, project) == ['clarify']


def test_exact_requirement_overrides_classification(fixture):
    root, _, request = fixture
    with patch.object(router, 'execute', return_value=('exact', ['laya', 'ast_grep'])) as execute:
        router.query(root, request | {'exact': True}, lambda *args: decision())
    assert execute.call_args.args[-1] is True


def test_summary_generation_needs_explicit_parameters_and_both_toggles(fixture):
    root, project, request = fixture
    set_preference(root, 'local_summaries', True)
    request.update(task_id='00000000-0000-0000-0000-000000000000', summary_action='start')
    assert 'summary' not in router.eligible_recipes(root, request, project)
    set_preference(root, 'llama_cpp', True)
    assert 'summary' in router.eligible_recipes(root, request, project)


def test_literal_pattern_is_forwarded_without_shell(fixture):
    root, project, request = fixture
    path = project / 'code.js'
    with patch('cli_tools.runtime_status', return_value={'available': True}), \
         patch('cli_tools.command', return_value=['ast-grep.exe']), \
         patch.object(router, 'run_command', return_value='original') as run:
        text, sequence = router.execute(root, 'ast_search', request, project, path, True)
    assert run.call_args.args[0] == ['ast-grep.exe', 'run', '--lang', 'javascript', '--pattern', 'console.log($A)', '--json=compact', str(path)]
    assert text == 'original' and sequence == ['laya', 'ast_grep']
