"""Generated zipapps import their own runtime and retain basic API behavior."""
import json
import subprocess
import sys
import zipfile

import pytest

import lib.ai_code_assets as assets
from lib.ai_package_server import generate_ai_package_server
from test_ai_package_server import app, package, snapshots, PAGE
from test_ai_server_runtime import request, running


def test_generated_archive_contains_static_entrypoint_and_runtime(app, package):
    with zipfile.ZipFile(app) as archive:
        members = archive.namelist()
        expected = (set(package['files']) | {target for source, target in assets.ASSET_LAYOUT.values()}
                    | {'ai_server_version.json', 'ai_server_front_page.md'})
        assert len(members) == len(set(members))
        assert set(members) == expected
        for name, (source, target) in assets.ASSET_LAYOUT.items():
            data = archive.read(target)
            assert data == assets.read_embedded_source(name)
            compile(data, target, 'exec')


def test_isolated_archive_imports_runtime_without_repository(app, tmp_path):
    unrelated = tmp_path / 'unrelated'
    unrelated.mkdir()
    result = subprocess.run([sys.executable, '-I', '-S', str(app), '--help'],
                            cwd=unrelated, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'Serve portable AI' in result.stdout


def test_basic_apis_and_role_validation_after_runtime_import(app, package):
    manifest = package['manifest']
    name = next(iter(manifest['chunks']))
    with running(app) as (port, log, errors):
        for path in ('/api', '/api/version', '/chunks', '/context/' + name):
            status, _, body = request(port, path)
            assert status == 200
            assert isinstance(json.loads(body), dict)
        assert request(port, '/')[2] == PAGE
        assert request(port, '/missing-route')[0] == 404
        document = dict(run_id=manifest['run_id'], source_chunk=name, role='analyst', results={})
        status, _, raw = request(port, '/validate/role/analyst/' + name,
                                 method='POST', body=json.dumps(document).encode())
        assert status == 200
        assert json.loads(raw) == dict(status='valid', run_id=manifest['run_id'], source_chunk=name)
        assert request(port, '/validate/role/analyst/' + name, method='POST', body=b'{}')[0] == 400
        assert request(port, '/result/' + name)[0] == 404
    assert not app.with_name(app.name + '.results').exists()


@pytest.mark.parametrize('name', list(assets.ASSET_FILES))
@pytest.mark.parametrize('data', [None, b'\xff', b'if:\n'])
def test_asset_failure_preserves_existing_zipapp(package, tmp_path, monkeypatch, name, data):
    originals = {key: assets.read_embedded_source(key) for key in assets.ASSET_FILES}
    asset_dir = tmp_path / 'assets'
    asset_dir.mkdir()
    for key, source in originals.items():
        if key != name:
            (asset_dir / assets.ASSET_FILES[key]).write_bytes(source)
    monkeypatch.setattr(assets, 'ASSET_DIR', str(asset_dir))
    if data is not None:
        (asset_dir / assets.ASSET_FILES[name]).write_bytes(data)
    output = tmp_path / 'existing.pyz'
    output.write_bytes(b'unchanged')
    with pytest.raises(ValueError, match='embedded Python asset'):
        generate_ai_package_server(package, PAGE, output)
    assert output.read_bytes() == b'unchanged'
    assert not list(tmp_path.glob('.serve-ai-*'))


@pytest.mark.parametrize('name', list(assets.ASSET_FILES))
def test_runtime_sources_are_read_fresh_for_each_generation(package, tmp_path, monkeypatch, name):
    originals = {key: assets.read_embedded_source(key) for key in assets.ASSET_FILES}
    asset_dir = tmp_path / 'assets'
    asset_dir.mkdir()
    for key, source in originals.items():
        (asset_dir / assets.ASSET_FILES[key]).write_bytes(source)
    monkeypatch.setattr(assets, 'ASSET_DIR', str(asset_dir))
    first, second = tmp_path / 'first.pyz', tmp_path / 'second.pyz'
    generate_ai_package_server(package, PAGE, first)
    marker = b'\n# Fresh static ' + name.encode('ascii') + b' source probe.\n'
    path = asset_dir / assets.ASSET_FILES[name]
    path.write_bytes(originals[name] + marker)
    generate_ai_package_server(package, PAGE, second)
    member = assets.ASSET_LAYOUT[name][1]
    with zipfile.ZipFile(first) as archive:
        assert marker not in archive.read(member)
    with zipfile.ZipFile(second) as archive:
        assert marker in archive.read(member)


def test_generation_reads_every_registered_asset_once(package, tmp_path, monkeypatch):
    calls = []
    original = assets.read_embedded_source
    def read(name):
        calls.append(name)
        return original(name)
    monkeypatch.setattr(assets, 'read_embedded_source', read)
    generate_ai_package_server(package, PAGE, tmp_path / 'once.pyz')
    assert calls == list(assets.ASSET_LAYOUT)


@pytest.mark.parametrize('fault', ['missing', 'duplicate'])
def test_registry_failure_preserves_existing_zipapp(package, tmp_path, monkeypatch, fault):
    layout = dict(assets.ASSET_LAYOUT)
    if fault == 'missing':
        layout.pop('package')
    else:
        layout['package'] = (layout['package'][0], layout['entrypoint'][1])
    monkeypatch.setattr(assets, 'ASSET_LAYOUT', layout)
    output = tmp_path / 'existing.pyz'
    output.write_bytes(b'unchanged')
    with pytest.raises(ValueError, match='embedded Python asset registry'):
        generate_ai_package_server(package, PAGE, output)
    assert output.read_bytes() == b'unchanged'
    assert not list(tmp_path.glob('.serve-ai-*'))
