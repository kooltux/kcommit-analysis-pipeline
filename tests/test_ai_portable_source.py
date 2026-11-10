"""Portable source indexing matches host identity, checksum and selection gates."""
import ast
import copy
import inspect
import json
import subprocess
import sys
import zipfile

import pytest

from lib import ai_contract, ai_source
from ai_runtime_helpers import runtime_namespace
from test_ai_package_server import app, package, snapshots


def test_portable_source_definitions_match_host(app):
    groups = {'source': (ai_source._fail, ai_source.index_source_commits,
                         ai_source._decode_source, ai_source.SourceIndex),
              'source_contract': (ai_contract.digest, ai_contract.input_schema, ai_contract.validate_chunk)}
    with zipfile.ZipFile(app) as archive:
        for name, definitions in groups.items():
            tree = ast.parse(archive.read('kcap_ai_runtime/' + name + '.py'))
            actual = {node.name: node for node in tree.body
                      if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
            for definition in definitions:
                expected = ast.parse(inspect.getsource(definition)).body[0]
                assert ast.dump(actual[definition.__name__]) == ast.dump(expected)


def test_runtime_index_matches_host_and_uses_shared_exception(app, package):
    host = ai_source.SourceIndex(package['manifest'],
        lambda name: package['files']['ai_analysis_input/' + name])
    with runtime_namespace(app) as values:
        index = values['SOURCE_INDEX']
        shared = sys.modules[values['__package__'] + '.source_contract']
        assert shared.AssessmentValidationError is values['AssessmentValidationError']
        assert shared.FIELDS == ai_contract.FIELDS
        assert shared.NAME.pattern == ai_contract.NAME.pattern
        assert shared.SHA.pattern == ai_contract.SHA.pattern
        assert shared.input_schema() == ai_contract.input_schema()
        assert index.raw == host.raw and index.chunks == host.chunks
        assert index.by_sha == host.by_sha and index.checksums == host.checksums
        assert index.select(list(reversed(list(host.by_sha)))) == host.select(list(host.by_sha))
        name = next(iter(host.chunks))
        index.context(name)['commits'].clear()
        assert index.context(name) == host.context(name)
        manifest = copy.deepcopy(package['manifest'])
        raw = dict(index.raw)
        first, second = sorted(raw)[:2]
        chunk = json.loads(raw[second])
        chunk['commits'][0]['commit'] = json.loads(raw[first])['commits'][0]['commit']
        raw[second] = ai_contract.encode(chunk)
        manifest['chunks'][second] = ai_contract.digest(raw[second])
        with pytest.raises(values['AssessmentValidationError'], match='Duplicate source SHA'):
            type(index)(manifest, raw.__getitem__)


@pytest.mark.parametrize('problem', ['checksum', 'json'])
def test_corrupt_source_is_rejected_before_startup(app, tmp_path, problem):
    with zipfile.ZipFile(app) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(files['ai_analysis_bundle_manifest.json'])
    name = next(iter(manifest['chunks']))
    data = b'{"invalid":NaN}'
    files['ai_analysis_input/' + name] = data
    if problem == 'json':
        manifest['chunks'][name] = ai_contract.digest(data)
        files['ai_analysis_bundle_manifest.json'] = ai_contract.encode(manifest)
    target = tmp_path / 'corrupt.pyz'
    with zipfile.ZipFile(target, 'w') as archive:
        for member, data in files.items():
            archive.writestr(member, data)
    result = subprocess.run([sys.executable, '-I', '-S', str(target), '--help'],
                            cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert ('checksum mismatch' if problem == 'checksum' else 'Invalid source JSON') in result.stderr
