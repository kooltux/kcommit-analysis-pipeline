"""Accumulated imports, validated compatibility reads and advisory report isolation."""
import copy

import pytest

from lib.ai_import_store import STORE_DIRECTORY, read_imported_results
from lib.ai_report import load_ai_results
from lib.commands.cmd_ai_import import import_results
from test_ai_import_sources import package, collection, record, write_json


def test_successive_partial_imports_replace_without_losing_other_shas(package, tmp_path):
    cfg, out, source = package
    first, second = sorted(source.by_sha)[:2]
    item = record(source)
    path = tmp_path / 'partial.json'
    write_json(path, collection(source, {first: item}))
    assert import_results(cfg, path)['analyzed_commits'] == 1
    write_json(path, collection(source, {second: item}))
    assert import_results(cfg, path)['analyzed_commits'] == 2
    replacement = dict(item, ai_summary='New assessment')
    write_json(path, collection(source, {first: replacement}))
    assert import_results(cfg, path)['analyzed_commits'] == 2
    expected = {first: replacement, second: item}
    assert load_ai_results(out) == expected
    (out / 'ai_analysis_results.json').unlink()
    assert load_ai_results(out) == expected
    assert (out / STORE_DIRECTORY / 'runs' / source.manifest['run_id']).is_dir()
    assert not (out / 'serve_ai.pyz.results').exists()


def test_legacy_migration_and_published_chunk_precedence(package, tmp_path):
    cfg, out, source = package
    first, second = sorted(source.by_sha)[:2]
    item = record(source)
    sidecar = out / 'ai_analysis_results.json'
    write_json(sidecar, {'run_id': source.manifest['run_id'], 'results': {first: item}})
    assert load_ai_results(out) == {first: item}
    path = tmp_path / 'next.json'
    write_json(path, collection(source, {second: item}))
    assert import_results(cfg, path)['analyzed_commits'] == 2
    write_json(sidecar, {'run_id': source.manifest['run_id'],
                         'results': {first: dict(item, ai_summary='Obsolete view')}})
    assert load_ai_results(out) == {first: item, second: item}


@pytest.mark.parametrize('problem', ['incoming', 'legacy'])
def test_validation_failure_does_not_touch_store_or_reports(package, tmp_path, problem):
    cfg, out, source = package
    sha = next(iter(source.by_sha))
    item = record(source)
    sidecar = out / 'ai_analysis_results.json'
    legacy = {'run_id': source.manifest['run_id'], 'results': {sha: item}}
    incoming = collection(source, {sha: dict(item, ai_summary='new')})
    (incoming if problem == 'incoming' else legacy)['results'][sha]['ai_is_bug_fix'] = 'FALSE'
    write_json(sidecar, legacy)
    path = tmp_path / 'invalid.json'
    write_json(path, incoming)
    before = {p.relative_to(out): p.read_bytes() for p in out.rglob('*') if p.is_file()}
    with pytest.raises(ValueError):
        import_results(cfg, path)
    assert before == {p.relative_to(out): p.read_bytes() for p in out.rglob('*') if p.is_file()}
    assert not (out / STORE_DIRECTORY).exists()


def test_other_run_sidecar_is_not_accumulated(package, tmp_path):
    cfg, out, source = package
    first, second = sorted(source.by_sha)[:2]
    item = record(source)
    write_json(out / 'ai_analysis_results.json', {'run_id': 'f' * 64, 'results': {first: item}})
    path = tmp_path / 'current.json'
    write_json(path, collection(source, {second: item}))
    assert import_results(cfg, path)['analyzed_commits'] == 1
    assert load_ai_results(out) == {second: item}


def test_partial_publication_keeps_previous_assessments(package, tmp_path, monkeypatch):
    cfg, out, source = package
    selected = []
    for name in sorted(source.chunks)[:2]:
        selected.append(next(sha for sha in sorted(source.by_sha) if source.by_sha[sha] == name))
    first, second = selected
    item = record(source)
    legacy = {first: item, second: copy.deepcopy(item)}
    write_json(out / 'ai_analysis_results.json', {'run_id': source.manifest['run_id'], 'results': legacy})
    path = tmp_path / 'replacement.json'
    replacement = dict(item, ai_summary='Published replacement')
    write_json(path, collection(source, {first: replacement}))
    from lib.ai_result_store import ResultStore
    original = ResultStore.write_chunk
    def fail_second(self, name, value):
        if name == source.by_sha[second]:
            raise OSError('second chunk failed')
        return original(self, name, value)
    monkeypatch.setattr(ResultStore, 'write_chunk', fail_second)
    with pytest.raises(OSError, match='second chunk failed'):
        import_results(cfg, path)
    assert load_ai_results(out) == {first: replacement, second: item}
    monkeypatch.setattr(ResultStore, 'write_chunk', original)
    assert import_results(cfg, path)['analyzed_commits'] == 2
    assert read_imported_results(source)[1] == {first: replacement, second: item}
