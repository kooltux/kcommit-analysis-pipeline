"""Shared source indexing verifies identities before exposing deterministic selections."""
import copy
import json

import pytest

from lib.ai_contract import AssessmentValidationError, digest, encode
from lib.ai_source import SourceIndex, index_source_commits


@pytest.fixture
def sources():
    manifest = dict(run_id='a' * 64, input_schema_checksum='b' * 64,
                    output_schema_checksum='c' * 64, total_commits=2, total_chunks=2, chunks={})
    raw = {}
    for number, sha in enumerate(('1' * 40, '2' * 40), 1):
        name = '%03d.json' % number
        item = dict(commit=sha, subject='', author_name='', author_email='', author_org='',
                    author_time=0, body='', files=[], stats={}, meta={}, product_evidence=[])
        chunk = dict(schema_version='1.0', pipeline_version='test', run_id=manifest['run_id'],
                     source_chunk=name, input_schema_checksum=manifest['input_schema_checksum'],
                     output_schema_checksum=manifest['output_schema_checksum'], total_commits=1,
                     chunk_info=dict(chunk_number=number, total_chunks=2,
                                     start_index=number - 1, end_index=number), commits=[item])
        raw[name] = encode(chunk)
        manifest['chunks'][name] = digest(raw[name])
    return manifest, raw


def test_source_index_reads_once_and_selects_deterministically(sources):
    manifest, raw = sources
    calls, progress = [], []
    original = copy.deepcopy(manifest)
    def read(name):
        calls.append(name)
        return raw[name]
    index = SourceIndex(manifest, read, lambda *args: progress.append(args))
    assert calls == ['001.json', '002.json']
    assert progress == [(1, 2, '001.json'), (2, 2, '002.json')]
    assert index.select(['2' * 40, '1' * 40]) == ('1' * 40, '2' * 40)
    assert index.select([]) == ()
    assert index.chunk_for('2' * 40) == '002.json'
    assert index.raw == raw and index.checksums == manifest['chunks']
    assert manifest == original
    index.record('1' * 40)['files'].append('changed')
    index.context('001.json')['commits'][0]['files'].append('changed')
    assert index.records['1' * 40]['files'] == []
    manifest['run_id'] = 'f' * 64
    assert index.manifest['run_id'] == 'a' * 64


@pytest.mark.parametrize('problem', ['checksum', 'identity', 'duplicate', 'total_commits', 'total_chunks'])
def test_source_index_rejects_invalid_packages(sources, problem):
    manifest, raw = sources
    if problem == 'checksum':
        raw['001.json'] += b' '
    elif problem in ('identity', 'duplicate'):
        chunk = json.loads(raw['002.json'])
        if problem == 'identity':
            chunk['run_id'] = 'f' * 64
        else:
            chunk['commits'][0]['commit'] = '1' * 40
        raw['002.json'] = encode(chunk)
        manifest['chunks']['002.json'] = digest(raw['002.json'])
    else:
        manifest[problem] += 1
    with pytest.raises(AssessmentValidationError) as caught:
        SourceIndex(manifest, raw.__getitem__)
    assert 'field' in caught.value.details


@pytest.mark.parametrize('data', [b'{"x":1,"x":2}', b'{"x":NaN}', b'\xff'])
def test_source_index_rejects_non_strict_json(sources, data):
    manifest, raw = sources
    raw['001.json'] = data
    manifest['chunks']['001.json'] = digest(data)
    with pytest.raises(AssessmentValidationError, match='Invalid source JSON'):
        SourceIndex(manifest, raw.__getitem__)


def test_source_index_rejects_paths_before_reading(sources):
    manifest, raw = sources
    manifest['chunks'] = {'../001.json': '0' * 64}
    with pytest.raises(AssessmentValidationError, match='Invalid source chunk path'):
        SourceIndex(manifest, lambda name: pytest.fail('read before path validation'))


@pytest.mark.parametrize('selection', ['1' * 40, ['1' * 40, '1' * 40], ['f' * 40], [{}]])
def test_invalid_selections_have_safe_diagnostics(sources, selection):
    manifest, raw = sources
    index = SourceIndex(manifest, raw.__getitem__)
    with pytest.raises(AssessmentValidationError) as caught:
        index.select(selection)
    assert set(caught.value.details) <= {'field', 'commit'}
    assert caught.value.details['field'] == 'results'


def test_preparation_identity_index_preserves_records_and_rejects_duplicates():
    item = {'commit': '1' * 40, 'body': 'source text'}
    assert index_source_commits([item]) == {'1' * 40: item}
    with pytest.raises(AssessmentValidationError, match='Duplicate source SHA'):
        index_source_commits([item, item])
    with pytest.raises(AssessmentValidationError) as caught:
        index_source_commits([{'commit': 'private assessment text'}])
    assert caught.value.details == {'field': 'commit'}
    assert 'private assessment text' not in str(caught.value)
