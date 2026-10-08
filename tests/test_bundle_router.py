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


def natural_request(root, request):
    set_preference(root, 'serena', True)
    return {key: value for key, value in request.items() if key not in ('pattern', 'language')}


def test_laya_runs_before_execution_and_records_no_prompt(fixture):
    root, project, request = fixture
    events = []
    def predict(*args):
        events.append('laya')
        assert 'symbols' in args[2]
        return decision('symbols')
    def execute(*args):
        events.append('execute')
        return 'result', ['laya', 'serena']
    with patch.object(router, 'execute', side_effect=execute):
        value = router.query(root, natural_request(root, request), predict)
    assert events == ['laya', 'execute']
    assert value['sequence'] == ['laya', 'serena']
    assert value['routing_basis'] == 'classifier'
    stored = (root / 'data/router/activity.json').read_text()
    assert request['intent'] not in stored and request['pattern'] not in stored


@pytest.mark.parametrize('bad', [
    {'route': 'powershell'}, {'confidence': float('nan')}, {'confidence': .79},
    {'truncated': True}, {'delivery': 'run-shell'}, {'route': 'clarify'}])
def test_bad_or_uncertain_decisions_never_execute(fixture, bad):
    root, _, request = fixture
    value = decision('symbols') | bad
    with patch.object(router, 'execute') as execute:
        with pytest.raises(ValueError):
            router.query(root, natural_request(root, request), lambda *args: value)
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
    request = natural_request(root, request)
    def predict(*args):
        set_preference(root, 'serena', False)
        return decision('symbols')
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


def test_caller_task_uuid_is_separate_from_summary_target(fixture):
    root, project, request = fixture
    caller = '11111111-1111-4111-8111-111111111111'
    assert router.validated_request(request | {'caller_task_id': caller})[0] == project
    with pytest.raises(ValueError, match='UUID'):
        router.validated_request(request | {'caller_task_id': 'private text'})


def test_exact_requirement_overrides_classification(fixture):
    root, _, request = fixture
    with patch.object(router, 'execute', return_value=('exact', ['laya', 'ast_grep'])) as execute:
        router.query(root, natural_request(root, request) | {'exact': True}, lambda *args: decision('symbols'))
    assert execute.call_args.args[-1] is True




def test_literal_pattern_is_forwarded_without_shell(fixture):
    root, project, request = fixture
    path = project / 'code.js'
    with patch('cli_tools.runtime_status', return_value={'available': True}), \
         patch('cli_tools.command', return_value=['ast-grep.exe']), \
         patch.object(router, 'run_command', return_value='[]') as run:
        text, sequence = router.execute(root, 'ast_search', request, project, path, True)
    assert run.call_args.args[0] == ['ast-grep.exe', 'run', '--lang', 'javascript', '--pattern', 'console.log($A)', '--json=compact', str(path)]
    assert json.loads(text)['total_matches'] == 0 and sequence == ['laya', 'ast_grep']
