"""Embedded source assets are syntax-checked without importing or running them."""
import pytest

import lib.ai_code_assets as assets


@pytest.mark.parametrize('name', ['entrypoint', 'package', 'contract_routes'])
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
