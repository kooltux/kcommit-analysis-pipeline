"""Accumulate validated local imports independently of the portable server store."""
import os
from pathlib import Path
import re

from lib.ai_contract import encode, validate_result
from lib.ai_canonical import CanonicalStore
from lib.ai_exchange import Progress, WorkPackage, decode
from lib.ai_result_store import ResultStore, _atomic_bytes

STORE_DIRECTORY = 'ai_import_results'
SIDECAR = 'ai_analysis_results.json'


def _legacy_results(package):
    path = package.root / SIDECAR
    try:
        value = decode(path.read_bytes())
    except FileNotFoundError:
        return {}
    if not isinstance(value, dict):
        raise ValueError('Invalid imported result sidecar')
    if value.get('run_id') != package.manifest['run_id']:
        return {}
    if set(value) != {'run_id', 'results'} or not isinstance(value['results'], dict):
        raise ValueError('Invalid imported result sidecar')
    for sha, item in value['results'].items():
        package.validate_item(sha, item)
    return value['results']


def read_imported_results(package):
    """Prefer canonical records; read intermediate stores and sidecars without writes."""
    def validate(name, value):
        return validate_result(value, package.index.context(name), package.schema,
                               package.index.checksums[name])
    root = package.root / STORE_DIRECTORY
    store = CanonicalStore(root, package.index, package.schema, package.analysis_id)
    results = store.assessments()
    legacy = ResultStore(root, package.index, validate)
    needed = {package.by_sha[sha] for sha in package.by_sha if sha not in results}
    if not package.by_sha:
        needed = set(package.chunks)
    missing = set()
    for name in sorted(needed):
        data = legacy.read_chunk(name)
        if data is None:
            missing.add(name)
        else:
            for sha, item in decode(data)['results'].items():
                results.setdefault(sha, item)
    if missing:
        for sha, item in _legacy_results(package).items():
            if package.by_sha[sha] in missing:
                results.setdefault(sha, item)
    return store, results


def publish_imported_results(package, store, results):
    """Prevalidate all findings, publish canonical records, then a compatibility view.

    Publication is atomic per SHA, not across the whole import or reports.
    Read-only legacy fallbacks preserve findings after interrupted migration.
    """
    records = {}
    for sha, item in results.items():
        package.validate_item(sha, item)
        records[sha] = dict(run_id=package.analysis_id, commit=sha, assessment=item)
    store.put_many(records)
    _atomic_bytes(os.fspath(package.root / SIDECAR),
                  encode({'run_id': package.manifest['run_id'], 'results': results}))


def load_report_results(outdir):
    """Read validated imported findings without writing or regenerating a package."""
    root = Path(outdir)
    manifest_path = root / 'ai_analysis_bundle_manifest.json'
    if not manifest_path.is_file():
        return {}
    manifest = decode(manifest_path.read_bytes())
    if not isinstance(manifest, dict):
        raise ValueError('Invalid AI source manifest')
    run_id = manifest.get('run_id')
    has_store = (isinstance(run_id, str) and re.fullmatch(r'[0-9a-f]{64}', run_id)
                 and (root / STORE_DIRECTORY / 'runs' / run_id).is_dir())
    has_store = has_store or any((root / STORE_DIRECTORY).glob(
        '[0-9a-f][0-9a-f]/[0-9a-f][0-9a-f]/*.json'))
    if not has_store:
        try:
            legacy = decode((root / SIDECAR).read_bytes())
        except FileNotFoundError:
            return {}
        if isinstance(legacy, dict) and legacy.get('run_id') != run_id:
            return {}
    package = WorkPackage({'paths': {'output_dir': os.fspath(root)}}, Progress('ai-report'))
    return read_imported_results(package)[1]
