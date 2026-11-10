"""Publication, replacement, corruption and source-isolation gates for result storage."""
import copy
import hashlib
import json

import pytest

import lib.ai_result_store as storage


class Source:
    def __init__(self, run_id='0' * 64):
        self.manifest = {'run_id': run_id}

    def context(self, name):
        if name != '001.json':
            raise ValueError('Unknown source chunk')
        return {}

    def chunk_for(self, sha):
        if sha not in ('a' * 40, 'b' * 40):
            raise ValueError('Unknown source SHA')
        return '001.json'


def validate(name, document):
    assert name == '001.json'
    if document.get('run_id') != '0' * 64:
        raise ValueError('Run mismatch')
    results = document['results']
    for sha, assessment in results.items():
        Source().chunk_for(sha)
        if not isinstance(assessment, dict) or not isinstance(assessment.get('value'), str):
            raise ValueError('Invalid assessment')
    if document['analyzed_commits'] != len(results) or document['total_commits'] != 2:
        raise ValueError('Count mismatch')
    expected = 'complete' if len(results) == 2 else 'partial'
    if document['analysis_status'] != expected:
        raise ValueError('Coverage mismatch')


def document(**values):
    results = {key * 40: {'value': value} for key, value in values.items()}
    return dict(run_id='0' * 64, source_chunk='001.json', total_commits=2,
                analyzed_commits=len(results),
                analysis_status='complete' if len(results) == 2 else 'partial', results=results)


def test_absent_reads_do_not_create_store(tmp_path):
    root = tmp_path / 'results'
    store = storage.ResultStore(root, Source(), validate)
    assert store.read_chunk('001.json') is None
    assert store.read_assessment('a' * 40) is None
    assert not root.exists()


def test_replacement_accumulation_bytes_and_defensive_reads(tmp_path):
    store = storage.ResultStore(tmp_path, Source(), validate)
    first = document(a='original')
    original = copy.deepcopy(first)
    assert store.write_chunk('001.json', first) == storage._encode(first)
    assert first == original
    store.write_chunk('001.json', document(b='second'))
    data = store.write_chunk('001.json', document(a='replacement'))
    assert data == store.read_chunk('001.json')
    assert json.loads(data) == document(a='replacement', b='second')
    value = store.read_assessment('a' * 40)
    value['value'] = 'mutated'
    assert store.read_assessment('a' * 40) == {'value': 'replacement'}
    blobs = list(tmp_path.glob('runs/*/commits/aa/' + 'a' * 40 + '/*.json'))
    assert len(blobs) == 2
    for blob in blobs:
        assert hashlib.sha256(blob.read_bytes()).hexdigest() == blob.stem


@pytest.mark.parametrize('failure', ['invalid', 'blob', 'index'])
def test_failure_preserves_previous_chunk(tmp_path, monkeypatch, failure):
    store = storage.ResultStore(tmp_path, Source(), validate)
    before = store.write_chunk('001.json', document(a='original'))
    candidate = document(a='replacement', b='new')
    if failure == 'invalid':
        candidate['results']['b' * 40] = {'value': 42}
    else:
        replace = storage.os.replace
        def fail(source, destination):
            if (failure == 'index') == ('chunks' in str(destination)):
                raise OSError('injected publication failure')
            return replace(source, destination)
        monkeypatch.setattr(storage.os, 'replace', fail)
    with pytest.raises((ValueError, OSError)):
        store.write_chunk('001.json', candidate)
    assert store.read_chunk('001.json') == before
    assert not list(tmp_path.rglob('.result-*'))


def test_invalid_first_upload_does_not_create_store(tmp_path):
    root = tmp_path / 'absent'
    store = storage.ResultStore(root, Source(), validate)
    candidate = document(a='original')
    candidate['run_id'] = '1' * 64
    with pytest.raises(ValueError):
        store.write_chunk('001.json', candidate)
    assert not root.exists()


def test_corruption_and_missing_blobs_are_not_absence(tmp_path):
    store = storage.ResultStore(tmp_path, Source(), validate)
    store.write_chunk('001.json', document(a='original'))
    blob = next(tmp_path.glob('runs/*/commits/aa/*/*.json'))
    blob.write_bytes(b'{}')
    with pytest.raises(ValueError, match='checksum mismatch'):
        store.read_chunk('001.json')
    blob.unlink()
    with pytest.raises(ValueError, match='Missing stored assessment'):
        store.read_chunk('001.json')


def test_run_and_source_isolation(tmp_path):
    store = storage.ResultStore(tmp_path, Source(), validate)
    store.write_chunk('001.json', document(a='original'))
    other = storage.ResultStore(tmp_path, Source('1' * 64), validate)
    assert other.read_chunk('001.json') is None
    with pytest.raises(ValueError):
        store.read_chunk('../001.json')
    with pytest.raises(ValueError):
        store.read_assessment('../escape')
