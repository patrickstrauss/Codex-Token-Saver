import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import bundle_router as router
from bundle_preferences import set_preference


@pytest.fixture
def search(tmp_path):
    root, project = tmp_path / 'bundle', tmp_path / 'project'
    project.mkdir()
    (project / 'code.js').write_text('console.log(answer);')
    for component in ('laya_router', 'ast_grep', 'headroom_local', 'serena'):
        set_preference(root, component, True)
    request = dict(intent='Locate call sites', project=str(project), path='code.js',
                   pattern='console.log($$$ARGS)', language='javascript', exact=True)
    return root, project, request


def test_explicit_pattern_routes_through_laya_without_model_load(search):
    root, _, request = search
    predictor = Mock(side_effect=AssertionError('Unnecessary model inference'))
    with patch.object(router, 'execute', return_value=('matches', ['laya', 'ast_grep'])):
        result = router.query(root, request, predictor)
    predictor.assert_not_called()
    assert result['sequence'] == ['laya', 'ast_grep']
    assert result['routing_basis'] == 'explicit_structural_search'
    assert result['routing_probability'] is None
    assert result['routing_ms'] == 0


@pytest.mark.parametrize('missing', ['pattern', 'language'])
def test_incomplete_structural_request_explains_required_arguments(search, missing):
    root, _, request = search
    del request[missing]
    with patch.object(router, 'execute') as execute, patch.object(router, 'classify') as classify:
        with pytest.raises(ValueError, match='pattern and language'):
            router.query(root, request)
    execute.assert_not_called()
    classify.assert_not_called()


@pytest.mark.parametrize('extra', [dict(symbol='foo'), dict(git_operation='status'),
    dict(browser_session='test')])
def test_conflicting_structural_operations_require_separate_requests(search, extra):
    root, _, request = search
    with patch.object(router, 'execute') as execute:
        with pytest.raises(ValueError, match='separate'):
            router.query(root, request | extra)
    execute.assert_not_called()


def test_disabled_ast_does_not_fall_back_to_reading_file(search):
    root, _, request = search
    set_preference(root, 'ast_grep', False)
    with patch.object(router, 'execute') as execute, patch.object(router, 'classify') as classify:
        with pytest.raises(ValueError, match='ast-grep.*Off'):
            router.query(root, request)
    execute.assert_not_called()
    classify.assert_not_called()


@pytest.mark.parametrize('extra', [dict(max_matches=True), dict(max_matches=0),
    dict(max_matches=201), dict(offset=-1), dict(offset=1.5)])
def test_invalid_pages_rejected(search, extra):
    _, _, request = search
    with pytest.raises(ValueError):
        router.validated_request(request | extra)


def match(project, line, text):
    return dict(file=str(project / 'code.js'), text=text, lines='redundant context',
        range={'start': {'line': line, 'column': 2}, 'end': {'line': line, 'column': 19}},
        metaVariables={'ARGS': 'redundant captures'})


def test_exact_results_are_small_stably_paged_and_report_omissions(search):
    root, project, request = search
    raw = json.dumps([match(project, 3, 'console.log(last)'), match(project, 0, 'console.log(first)'),
                      match(project, 1, 'console.log(middle)')])
    with patch('cli_tools.runtime_status', return_value={'available': True}), \
         patch('cli_tools.command', return_value=['ast-grep.exe']), \
         patch.object(router, 'run_command', return_value=raw), \
         patch('command_compression.CommandCompressor') as compressor:
        text, sequence = router.execute(root, 'ast_search', request | {'max_matches': 1, 'offset': 1},
                                        project, project / 'code.js', False)
    page = json.loads(text)
    assert page['total_matches'] == 3 and page['returned_matches'] == 1
    assert page['next_offset'] == 2 and page['truncated'] is True
    assert page['matches'] == [dict(file='code.js', line=2, column=3, end_line=2, end_column=20,
                                    text='console.log(middle)')]
    assert sequence == ['laya', 'ast_grep']
    assert 'metaVariables' not in text and 'redundant' not in text
    compressor.assert_not_called()


def test_zero_matches_and_last_page_are_explicit(search):
    _, project, _ = search
    page = json.loads(router.ast_search_page('[]', project, {}))
    assert page['matches'] == [] and page['total_matches'] == 0
    assert page['next_offset'] is None and page['truncated'] is False
    raw = json.dumps([match(project, 0, 'console.log(answer)')])
    page = json.loads(router.ast_search_page(raw, project, {'offset': 1}))
    assert page['matches'] == [] and page['next_offset'] is None


def test_default_page_is_bounded_and_preserves_match_text(search):
    _, project, _ = search
    raw = json.dumps([match(project, i, 'console.log("exact ' + str(i) + '")') for i in range(51)])
    page = json.loads(router.ast_search_page(raw, project, {}))
    assert page['returned_matches'] == 50 and page['next_offset'] == 50
    assert page['matches'][0]['text'] == 'console.log("exact 0")'


def test_toggle_change_after_typed_routing_blocks_execution(search):
    root, project, request = search
    original = router.eligible_recipes
    def eligibility(*args):
        result = original(*args)
        set_preference(root, 'ast_grep', False)
        return result
    with patch.object(router, 'eligible_recipes', side_effect=eligibility), patch.object(router, 'run_command') as run:
        with pytest.raises(RuntimeError, match='disabled'):
            router.query(root, request)
    run.assert_not_called()


@pytest.mark.parametrize('raw', ['{}', 'not json', '[{"text": "partial"}]'])
def test_malformed_results_do_not_look_like_success(search, raw):
    _, project, _ = search
    with pytest.raises(RuntimeError, match='Invalid ast-grep'):
        router.ast_search_page(raw, project, {})


def test_pagination_requires_structural_operation(search):
    _, _, request = search
    for key in ('pattern', 'language'):
        del request[key]
    with pytest.raises(ValueError, match='pagination'):
        router.validated_request(request | {'offset': 1})
