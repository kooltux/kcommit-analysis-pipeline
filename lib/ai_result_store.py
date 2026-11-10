"""Run-bound immutable assessment blobs with atomically published chunk indexes."""
import hashlib
import json
import os
import re
import tempfile
import threading


def _encode(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def _decode(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate stored JSON key')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Invalid stored JSON constant')
    return json.loads(data.decode('utf-8'), object_pairs_hook=unique, parse_constant=constant)


def _atomic_bytes(path, data):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=directory, prefix='.result-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ResultStore:
    """One writer instance per root; immutable blobs keep concurrent reads coherent.

    The validator accepts (chunk_name, document) and raises on invalid input.
    Failed publication can leave unreferenced blobs, never a partial live index.
    This is not an interprocess writer lock or a cross-chunk transaction.
    """

    def __init__(self, root, source_index, validate):
        run_id = source_index.manifest['run_id']
        if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{64}', run_id):
            raise ValueError('Invalid result-store run identity')
        if not callable(validate):
            raise ValueError('Result-store validator must be callable')
        self.root = os.path.abspath(root)
        self.directory = os.path.join(self.root, 'runs', run_id)
        self.source = source_index
        self.validate = validate
        self._lock = threading.RLock()

    def _index_path(self, name):
        self.source.context(name)
        key = hashlib.sha256(name.encode('utf-8')).hexdigest()
        return os.path.join(self.directory, 'chunks', key + '.json')

    def _blob_path(self, name, sha, checksum):
        if self.source.chunk_for(sha) != name:
            raise ValueError('Stored assessment source mismatch')
        if not isinstance(checksum, str) or not re.fullmatch(r'[0-9a-f]{64}', checksum):
            raise ValueError('Invalid stored assessment checksum')
        return os.path.join(self.directory, 'commits', sha[:2], sha, checksum + '.json')

    def read_chunk(self, name):
        """Return a validated canonical envelope, or None for an absent chunk."""
        path = self._index_path(name)
        try:
            with open(path, 'rb') as stream:
                document = _decode(stream.read())
        except FileNotFoundError:
            try:
                with open(os.path.join(self.root, name), 'rb') as stream:
                    document = _decode(stream.read())
            except FileNotFoundError:
                return None
            self.validate(name, document)
            return _encode(document)
        if not isinstance(document, dict) or not isinstance(document.get('results'), dict):
            raise ValueError('Invalid stored chunk index')
        results = {}
        for sha, checksum in document['results'].items():
            try:
                with open(self._blob_path(name, sha, checksum), 'rb') as stream:
                    data = stream.read()
            except FileNotFoundError:
                raise ValueError('Missing stored assessment blob') from None
            if hashlib.sha256(data).hexdigest() != checksum:
                raise ValueError('Stored assessment checksum mismatch')
            results[sha] = _decode(data)
        document['results'] = results
        self.validate(name, document)
        return _encode(document)

    def read_assessment(self, sha):
        """Return a defensive assessment value, or None if not yet analyzed."""
        data = self.read_chunk(self.source.chunk_for(sha))
        return None if data is None else _decode(data)['results'].get(sha)

    def write_chunk(self, name, document):
        """Validate first; replace supplied SHAs and preserve other accepted SHAs."""
        candidate = _decode(_encode(document))
        self._index_path(name)
        self.validate(name, candidate)
        with self._lock:
            previous = self.read_chunk(name)
            results = {} if previous is None else _decode(previous)['results']
            results.update(candidate['results'])
            candidate['results'] = results
            candidate['analyzed_commits'] = len(results)
            candidate['analysis_status'] = ('complete' if len(results) == candidate['total_commits']
                                            else 'partial')
            self.validate(name, candidate)
            data = _encode(candidate)
            index = dict(candidate, results={})
            for sha, assessment in sorted(results.items()):
                blob = _encode(assessment)
                checksum = hashlib.sha256(blob).hexdigest()
                _atomic_bytes(self._blob_path(name, sha, checksum), blob)
                index['results'][sha] = checksum
            _atomic_bytes(self._index_path(name), _encode(index))
            return data
