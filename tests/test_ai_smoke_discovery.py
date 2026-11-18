"""The smoke tool checks both current APIs and detects malformed discovery."""
import runpy
import shutil
from pathlib import Path
import pytest
from test_ai_batch_layout import prepare

@pytest.fixture
def tool():
    return runpy.run_path(str(Path(__file__).resolve().parents[1] / 'run_tests_ai'))['check_discovery'].__globals__

@pytest.mark.parametrize('count', [0, 1, 9])
def test_full_smoke_with_generated_zipapp(tool, tmp_path, count):
    if shutil.which('curl') is None:
        pytest.skip('curl required')
    cfg, cache, out, summary, manifest = prepare(tmp_path, count=count)
    tool['smoke'](out / 'serve_ai.pyz')

@pytest.mark.parametrize('fault', ['missing_shared', 'cross_prefix', 'missing_description', 'paginated_catalog'])
def test_smoke_detects_invalid_catalog(tool, monkeypatch, fault):
    routes = [dict(method='GET', path='/v1' + p, description='Entry', examples=[], path_parameters={}) for p in ('/api', '/version', '/contract', '/prompt/<name>', '/schema/<name>')]
    api = dict(run_id='r', routes=routes)
    if fault == 'missing_shared':
        routes.pop()
    elif fault == 'cross_prefix':
        routes[0]['path'] = '/v2/api'
    elif fault == 'missing_description':
        routes[0].pop('description')

    def expect(base, path, status=200, **kwargs):
        import json
        if status == 404:
            return b'{}'
        if '?' in path and fault == 'paginated_catalog':
            return b'{}'
        return json.dumps(api).encode()
    monkeypatch.setitem(tool, 'expect', expect)
    with pytest.raises(AssertionError):
        tool['check_discovery']('unused')
