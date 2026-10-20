"""Grouping-independent AI import, identity checks and progress regressions."""
import json
import zipfile

import pytest

from lib.ai_exchange import Progress, WorkPackage, decode
from lib.commands.cmd_ai_import import import_results
from test_ai_batch_layout import prepare


@pytest.fixture
def package(tmp_path, monkeypatch):
    cfg, cache, out, _, _ = prepare(tmp_path, count=5)
    monkeypatch.setattr('lib.stages.st07_ai_report.run', lambda *args: None)
    return cfg, out, WorkPackage(cfg, Progress('test'))


def record(package):
    props = package.schema['properties']['results']['additionalProperties']['properties']
    value = {}
    for key, spec in props.items():
        value[key] = (False if spec['type'] == 'boolean' else [] if spec['type'] == 'array'
                      else spec.get('enum', ['Manual assessment'])[0])
    value['ai_risks_if_not_backported'] = ['none']
    return value


def collection(package, results):
    return dict(schema_version='1.0', run_id=package.manifest['run_id'],
                input_schema_checksum=package.manifest['input_schema_checksum'],
                output_schema_checksum=package.manifest['output_schema_checksum'], results=results)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


@pytest.mark.parametrize('layout', ['zip', 'chunks', 'single', 'individual'])
def test_import_grouping_equivalence(package, tmp_path, layout):
    cfg, out, source = package
    results = {sha: record(source) for sha in source.by_sha}
    dest = tmp_path / 'returned'
    if layout == 'single':
        dest = dest.with_suffix('.json')
        write_json(dest, collection(source, results))
    elif layout == 'individual':
        for index, (sha, item) in enumerate(results.items()):
            write_json(dest / 'arbitrary' / f'{index}.json', collection(source, {sha: item}))
    else:
        for name in source.chunks:
            records = {sha: item for sha, item in results.items() if source.by_sha[sha] == name}
            write_json(dest / name, source.envelope(name, records))
        if layout == 'zip':
            bundle_path = tmp_path / 'returned.zip'
            with zipfile.ZipFile(bundle_path, 'w') as bundle:
                bundle.writestr('ai_analysis_bundle_manifest.json', source.manifest_bytes)
                for name, data in source.raw.items():
                    bundle.writestr('ai_analysis_input/' + name, data)
                    bundle.write(dest / name, 'results/' + name)
            dest = bundle_path
    assert import_results(cfg, dest) == {'run_id': source.manifest['run_id'], 'analyzed_commits': 5}
    assert decode((out / 'ai_analysis_results.json').read_bytes())['results'] == results


@pytest.mark.parametrize('individual', [False, True])
def test_thousand_commit_grouping(tmp_path, monkeypatch, individual):
    cfg, _, out, _, _ = prepare(tmp_path, count=1001)
    monkeypatch.setattr('lib.stages.st07_ai_report.run', lambda *args: None)
    source = WorkPackage(cfg, Progress('test'))
    results = {sha: record(source) for sha in source.by_sha}
    dest = tmp_path / 'many'
    if individual:
        for index, (sha, item) in enumerate(results.items()):
            write_json(dest / f'{index:04d}.json', collection(source, {sha: item}))
    else:
        dest = dest.with_suffix('.json')
        write_json(dest, collection(source, results))
    assert import_results(cfg, dest)['analyzed_commits'] == 1001
    assert decode((out / 'ai_analysis_results.json').read_bytes())['results'] == results


@pytest.mark.parametrize('problem', ['unknown', 'boolean', 'identity', 'schema', 'extra'])
def test_invalid_import_preserves_sidecar(package, tmp_path, problem):
    cfg, out, source = package
    sha = next(iter(source.by_sha))
    value = collection(source, {sha: record(source)})
    if problem == 'unknown':
        value['results'] = {'f' * 40: record(source)}
    elif problem == 'boolean':
        value['results'][sha]['ai_is_bug_fix'] = 'FALSE'
    elif problem == 'identity':
        value['run_id'] = '0' * 64
    elif problem == 'schema':
        value['output_schema_checksum'] = '0' * 64
    else:
        value['invented'] = True
    sidecar = out / 'ai_analysis_results.json'
    sidecar.write_bytes(b'unchanged')
    path = tmp_path / 'bad.json'
    write_json(path, value)
    with pytest.raises(ValueError):
        import_results(cfg, path)
    assert sidecar.read_bytes() == b'unchanged'


def test_duplicate_json_keys_rejected():
    with pytest.raises(ValueError, match='Duplicate JSON key'):
        decode('{"results": {}, "results": {}}')


def test_import_duplicates_first_wins(package, tmp_path, capsys):
    cfg, out, source = package
    sha = next(iter(source.by_sha))
    item = record(source)
    folder = tmp_path / 'duplicates'
    write_json(folder / 'a.json', collection(source, {sha: item}))
    write_json(folder / 'b.json', collection(source, {sha: item}))
    write_json(folder / 'z.json', collection(source, {sha: dict(item, ai_summary='Changed')}))
    assert import_results(cfg, folder)['analyzed_commits'] == 1
    assert decode((out / 'ai_analysis_results.json').read_bytes())['results'][sha] == item
    stderr = capsys.readouterr().err
    assert 'WARNING conflicting duplicate ' + sha in stderr
    assert 'ai_summary' in stderr and 'retained' in stderr and 'rejected' in stderr
    assert 'a.json' in stderr and 'z.json' in stderr
    assert '1 identical duplicates skipped; 1 conflicting duplicates rejected' in stderr
    assert 'Discovered 3 files' in stderr and 'Done:' in stderr
