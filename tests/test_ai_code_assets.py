"""Embedded source assets are syntax-checked without importing or running them."""
import pytest

import lib.ai_code_assets as assets


@pytest.mark.parametrize('name', list(assets.ASSET_FILES))
def test_static_embedded_sources_are_python_bytes(name):
    data = assets.read_embedded_source(name)
    assert isinstance(data, bytes)
    compile(data.decode('utf-8'), assets.ASSET_FILES[name], 'exec')


def test_reading_embedded_source_does_not_execute_it(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, 'ASSET_DIR', str(tmp_path))
    source = b'raise RuntimeError("must not execute during generation")\n'
    (tmp_path / assets.ASSET_FILES['entrypoint']).write_bytes(source)
    assert assets.read_embedded_source('entrypoint') == source


@pytest.mark.parametrize('name', ['unknown', '../entrypoint'])
def test_unknown_embedded_source_is_rejected(name):
    with pytest.raises(ValueError, match='Unknown embedded Python asset'):
        assets.read_embedded_source(name)


def test_missing_embedded_source_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, 'ASSET_DIR', str(tmp_path))
    with pytest.raises(ValueError, match='Cannot read embedded Python asset'):
        assets.read_embedded_source('entrypoint')


@pytest.mark.parametrize('data', [b'\xff', b'if:\n'])
def test_invalid_embedded_source_is_rejected(tmp_path, monkeypatch, data):
    monkeypatch.setattr(assets, 'ASSET_DIR', str(tmp_path))
    (tmp_path / assets.ASSET_FILES['entrypoint']).write_bytes(data)
    with pytest.raises(ValueError, match='Invalid embedded Python asset'):
        assets.read_embedded_source('entrypoint')


def test_archive_layout_covers_exactly_the_runtime_members():
    assert set(assets.ASSET_LAYOUT) == set(assets.ASSET_FILES)
    assert {name: source for name, (source, target) in assets.ASSET_LAYOUT.items()} == assets.ASSET_FILES
    assert {target for source, target in assets.ASSET_LAYOUT.values()} == {
        '__main__.py', 'kcap_ai_runtime/__init__.py', 'kcap_ai_runtime/server.py',
        'kcap_ai_runtime/workflow.py', 'kcap_ai_runtime/contract_routes.py',
        'kcap_ai_runtime/validation.py', 'kcap_ai_runtime/prompt_body.py',
    }
    assert len(assets.ASSET_LAYOUT) == 7


def test_archive_loader_reads_each_asset_once_without_execution(monkeypatch):
    calls = []
    def read(name):
        calls.append(name)
        return ('raise RuntimeError(' + repr(name) + ')\n').encode('utf-8')
    monkeypatch.setattr(assets, 'read_embedded_source', read)
    result = assets.read_embedded_archive()
    assert calls == list(assets.ASSET_LAYOUT)
    for name, (source, target) in assets.ASSET_LAYOUT.items():
        assert result[target] == ('raise RuntimeError(' + repr(name) + ')\n').encode('utf-8')


@pytest.mark.parametrize('fault', ['missing', 'duplicate'])
def test_invalid_archive_layout_is_rejected_before_reading(monkeypatch, fault):
    layout = dict(assets.ASSET_LAYOUT)
    if fault == 'missing':
        layout.pop('package')
    else:
        layout['package'] = (layout['package'][0], layout['entrypoint'][1])
    monkeypatch.setattr(assets, 'ASSET_LAYOUT', layout)
    monkeypatch.setattr(assets, 'read_embedded_source', lambda name: pytest.fail('read before registry validation'))
    with pytest.raises(ValueError, match='embedded Python asset registry'):
        assets.read_embedded_archive()
