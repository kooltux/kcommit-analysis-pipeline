"""Canonical export/import, regrouping, legacy fallback and publication safety."""
import copy
import json
from pathlib import Path
import zipfile

import pytest

from lib.ai_canonical import record_path
from lib.ai_contract import digest, encode, result_properties, validate_result
from lib.ai_exchange import Progress, WorkPackage, read_assessments
from lib.ai_import_store import STORE_DIRECTORY, read_imported_results
from lib.ai_report import load_ai_results
from lib.ai_result_store import ResultStore
from lib.commands.cmd_ai_import import import_results
from lib.stages.st08_prepare_ai import run as prepare_ai
from test_ai_import_sources import package, collection, record, write_json
from test_ai_server_runtime import request, running
from ai_http_helpers import submit_selection


def canonical(source, sha, item):
    return dict(run_id=source.analysis_id, commit=sha, assessment=item)


def bundle(path, source, results, problem=None):
    manifest = copy.deepcopy(source.manifest)
    members = {'ai_analysis_input/' + name: data for name, data in source.raw.items()}
    members.update({'ai_contract/' + name: (source.root / 'ai_contract' / name).read_bytes()
                    for name in manifest['contract_assets']})
    for sha, item in results.items():
        value = canonical(source, sha, item)
        member = 'results/' + record_path(sha)
        if problem == 'run':
            value['run_id'] = 'f' * 64
        elif problem == 'filename':
            member = 'results/' + record_path(next(key for key in source.by_sha if key != sha))
        members[member] = encode(value)
    if problem == 'identity':
        manifest['analysis_id'] = 'f' * 64
    elif problem == 'contract':
        name = 'ai_contract/' + next(iter(manifest['contract_assets']))
        members[name] += b'\n'
    elif problem == 'source':
        name = next(iter(source.raw))
        value = json.loads(source.raw[name])
        value['commits'][0]['subject'] = 'Foreign source content'
        members['ai_analysis_input/' + name] = encode(value)
        manifest['chunks'][name] = digest(members['ai_analysis_input/' + name])
    elif problem == 'extra':
        members['../escape'] = b'forbidden'
    members['ai_analysis_bundle_manifest.json'] = encode(manifest)
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in members.items():
            archive.writestr(name, data)


@pytest.mark.parametrize('prefix', ['/v1', '/v2'])
def test_real_versioned_export_import_uses_identical_canonical_records(package, tmp_path, prefix):
    cfg, out, source = package
    selected = sorted(source.by_sha)[:2]
    item = record(source)
    schemas = {role: json.loads((out / 'ai_contract/schemas' / (role + '.json')).read_bytes())
               for role in ('analyst', 'cve', 'reviewer')}
    documents = {role: dict(run_id=source.analysis_id, role=role,
                           results={sha: {key: item[key] for key in result_properties(schema)}
                                    for sha in selected}) for role, schema in schemas.items()}
    app = out / 'serve_ai.pyz'
    with running(app) as (port, log, errors):
        assert submit_selection(port, prefix, documents)[0] == 200
        status, _, data = request(port, prefix + '/export')
        assert status == 200
    path = tmp_path / 'canonical.zip'
    path.write_bytes(data)
    assert import_results(cfg, path)['analyzed_commits'] == 2
    assert load_ai_results(out) == {sha: item for sha in selected}
    for sha in selected:
        local = out / STORE_DIRECTORY / record_path(sha)
        live = Path(str(app) + '.results') / record_path(sha)
        assert local.read_bytes() == live.read_bytes()
    (out / 'ai_analysis_results.json').unlink()
    assert load_ai_results(out) == {sha: item for sha in selected}


def test_regrouping_retains_local_results_and_accepts_original_export(package, tmp_path):
    cfg, out, source = package
    first, second = sorted(source.by_sha)[:2]
    item = record(source)
    loose = tmp_path / (first + '.json')
    write_json(loose, canonical(source, first, item))
    import_results(cfg, loose)
    original = tmp_path / 'original.zip'
    bundle(original, source, {second: item})
    previous = (out / STORE_DIRECTORY / record_path(first)).read_bytes()
    cfg['ai'].update(chunk_size=1, batch_size=3)
    prepare_ai(cfg, cfg['paths']['cache_dir'], str(out))
    regrouped = WorkPackage(cfg, Progress('test'))
    assert regrouped.analysis_id == source.analysis_id
    assert regrouped.manifest['run_id'] != source.manifest['run_id']
    assert load_ai_results(out) == {first: item}
    assert import_results(cfg, original)['analyzed_commits'] == 2
    assert load_ai_results(out) == {first: item, second: item}
    assert (out / STORE_DIRECTORY / record_path(first)).read_bytes() == previous


@pytest.mark.parametrize('problem', ['run', 'identity', 'filename', 'contract', 'source', 'extra'])
def test_bad_canonical_bundle_does_not_publish(package, tmp_path, problem):
    cfg, out, source = package
    sha = next(iter(source.by_sha))
    path = tmp_path / 'invalid.zip'
    bundle(path, source, {sha: record(source)}, problem)
    before = {p.relative_to(out): p.read_bytes() for p in out.rglob('*') if p.is_file()}
    with pytest.raises(ValueError):
        import_results(cfg, path)
    assert before == {p.relative_to(out): p.read_bytes() for p in out.rglob('*') if p.is_file()}
    assert not (out / STORE_DIRECTORY).exists()


def test_intermediate_store_is_read_only_until_a_valid_import_migrates_it(package, tmp_path):
    cfg, out, source = package
    first, second = sorted(source.by_sha)[0], sorted(source.by_sha)[-1]
    item = record(source)
    def validate(name, value):
        return validate_result(value, source.chunks[name], source.schema, source.index.checksums[name])
    old = ResultStore(out / STORE_DIRECTORY, source.index, validate)
    name = source.by_sha[first]
    old.write_chunk(name, source.envelope(name, {first: item}))
    before = {p: p.read_bytes() for p in (out / STORE_DIRECTORY).rglob('*') if p.is_file()}
    assert read_imported_results(source)[1] == {first: item}
    assert before == {p: p.read_bytes() for p in (out / STORE_DIRECTORY).rglob('*') if p.is_file()}
    path = tmp_path / (second + '.json')
    write_json(path, canonical(source, second, item))
    assert import_results(cfg, path)['analyzed_commits'] == 2
    assert load_ai_results(out) == {first: item, second: item}
    assert all((out / STORE_DIRECTORY / record_path(sha)).is_file() for sha in (first, second))
    assert all(p.read_bytes() == data for p, data in before.items())


def test_loose_canonical_filename_must_match_record(package, tmp_path):
    cfg, out, source = package
    sha = next(iter(source.by_sha))
    path = tmp_path / 'wrong.json'
    write_json(path, canonical(source, sha, record(source)))
    with pytest.raises(ValueError, match='filename'):
        import_results(cfg, path)
    assert not (out / STORE_DIRECTORY).exists()


def test_mixed_input_batch_keeps_first_wins_policy(package, tmp_path, capsys):
    cfg, out, source = package
    sha = next(iter(source.by_sha))
    item = record(source)
    root = tmp_path / 'mixed'
    write_json(root / 'legacy.json', collection(source, {sha: item}))
    write_json(root / 'z' / (sha + '.json'), canonical(source, sha, dict(item, ai_summary='Conflicting')))
    assert import_results(cfg, root)['analyzed_commits'] == 1
    assert load_ai_results(out) == {sha: item}
    assert 'conflicting duplicate' in capsys.readouterr().err
