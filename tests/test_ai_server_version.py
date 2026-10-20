"""The standalone server reports the manifest version captured at generation."""
import json
import zipfile
import pytest
import lib.ai_serve_script_gen as generator
from test_ai_server_runtime import app, basic, request, running


def metadata(path):
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read('ai_server_version.json'))


def test_version_is_read_fresh_and_pinned_in_each_zipapp(app, tmp_path, monkeypatch):
    source = tmp_path / 'tool-manifest.json'
    monkeypatch.setattr(generator, 'TOOL_MANIFEST_PATH', str(source))
    first, second = tmp_path / 'first.pyz', tmp_path / 'second.pyz'
    source.write_text(json.dumps({'version': 'v90.1.2'}))
    generator.generate_ai_serve_script(str(app.parent), str(first))
    source.write_text(json.dumps({'version': 'v90.1.3'}))
    generator.generate_ai_serve_script(str(app.parent), str(second))
    source.unlink()
    assert metadata(first) == {'tool_version': 'v90.1.2', 'version_source': 'MANIFEST.json',
                               'captured_at': 'zipapp_generation'}
    assert metadata(second)['tool_version'] == 'v90.1.3'


@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
def test_version_endpoint_is_portable_authenticated_and_discoverable(app, tmp_path, monkeypatch, auth):
    source = tmp_path / 'tool-manifest.json'
    source.write_text(json.dumps({'version': 'v90.1.2'}))
    monkeypatch.setattr(generator, 'TOOL_MANIFEST_PATH', str(source))
    bundle_path = app.parent / 'ai_analysis_bundle_manifest.json'
    bundle = json.loads(bundle_path.read_text())
    bundle['pipeline_version'] = 'v1.0.0'
    bundle_path.write_text(json.dumps(bundle))
    target = tmp_path / 'versioned.pyz'
    generator.generate_ai_serve_script(str(app.parent), str(target))
    expected = metadata(target)
    source.unlink()
    with running(target, auth=auth) as (port, log, errors):
        if auth:
            assert request(port, '/api/version')[0] == 401
        token = basic(auth) if auth else None
        code, headers, raw = request(port, '/api/version?limit=1&offset=999', authorization=token)
        assert code == 200 and headers['Content-Type'] == 'application/json'
        assert int(headers['Content-Length']) == len(raw)
        assert json.loads(raw) == expected
        assert expected['tool_version'] != bundle['pipeline_version']
        catalog = json.loads(request(port, '/api', authorization=token)[2])
        route = next(r for r in catalog['routes'] if r['method'] == 'GET' and r['path'] == '/api/version')
        assert route['response_content_type'] == 'application/json'
        assert 'query_parameters' not in route
        assert request(port, '/api/version/extra', authorization=token)[0] == 404


@pytest.mark.parametrize('value', [None, '', ' ', True, 3, []])
def test_invalid_manifest_version_does_not_overwrite_output(app, tmp_path, monkeypatch, value):
    source = tmp_path / 'tool-manifest.json'
    source.write_text(json.dumps({'version': value}))
    monkeypatch.setattr(generator, 'TOOL_MANIFEST_PATH', str(source))
    target = tmp_path / 'existing.pyz'
    target.write_bytes(b'unchanged')
    with pytest.raises(ValueError, match='version'):
        generator.generate_ai_serve_script(str(app.parent), str(target))
    assert target.read_bytes() == b'unchanged'


def test_generated_version_matches_current_tool_manifest(app):
    with open(generator.TOOL_MANIFEST_PATH, encoding='utf-8') as stream:
        current = json.load(stream)
    assert metadata(app)['tool_version'] == current['version']
