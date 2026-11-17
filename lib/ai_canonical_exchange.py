"""Read canonical result bundles independently of their source delivery grouping."""
import re

from lib.ai_canonical import record_path, validate_record
from lib.ai_contract import digest
from lib.ai_result_store import _decode
from lib.ai_source import SourceIndex


def is_canonical_bundle(names):
    return any(name.startswith('ai_contract/') or re.fullmatch(
        r'results/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{40}[.]json', name) for name in names)


def read_canonical_bundle(package, bundle, accepted, progress):
    names = bundle.namelist()
    if len(names) != len(set(names)):
        raise ValueError('Duplicate canonical bundle member')
    try:
        manifest = _decode(bundle.read('ai_analysis_bundle_manifest.json'))
    except (KeyError, UnicodeError, ValueError) as exc:
        raise ValueError('Invalid canonical bundle manifest') from exc
    if not isinstance(manifest, dict) or manifest.get('analysis_id') != package.analysis_id:
        raise ValueError('Canonical bundle belongs to another analysis')
    for field in ('contract_assets', 'input_schema_checksum', 'output_schema_checksum', 'prompt_checksum'):
        if manifest.get(field) != package.manifest.get(field):
            raise ValueError('Canonical bundle contract identity mismatch: ' + field)
    chunks = manifest.get('chunks')
    if not isinstance(chunks, dict) or any(not isinstance(name, str) for name in chunks):
        raise ValueError('Invalid canonical source inventory')
    required = ({'ai_analysis_bundle_manifest.json'}
                | {'ai_contract/' + name for name in package.manifest['contract_assets']}
                | {'ai_analysis_input/' + name for name in chunks})
    allowed_results = {'results/' + record_path(sha) for sha in package.by_sha}
    if required - set(names) or set(names) - required - allowed_results:
        raise ValueError('Missing or unknown canonical bundle member')
    for name, expected in package.manifest['contract_assets'].items():
        if digest(bundle.read('ai_contract/' + name)) != expected:
            raise ValueError('Canonical bundle contract checksum mismatch: ' + name)
    try:
        source = SourceIndex(manifest, lambda name: bundle.read('ai_analysis_input/' + name))
    except KeyError as exc:
        raise ValueError('Missing canonical bundle source') from exc
    if source.records != package.index.records:
        raise ValueError('Canonical bundle source set differs from the local work package')
    files = sorted(set(names) & allowed_results)
    for index, name in enumerate(files, 1):
        value = _decode(bundle.read(name))
        sha = name.rsplit('/', 1)[1][:-5]
        validate_record(value, package.index, package.schema, package.analysis_id, sha)
        accepted.add(sha, value['assessment'], str(bundle.filename or '<memory>') + '!' + name)
        progress.say(f'Read canonical result {index}/{len(files)}: {name}', index in (1, len(files)))
