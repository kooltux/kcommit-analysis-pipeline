"""Validate AI results against the current work package and regenerate reports."""
import json
import os
import zipfile

from lib.ai_contract import digest, validate_chunk, validate_result
from lib.commands.base import load_cfg
from lib.config import load_json, save_json
from lib.manifest import CACHE_FILES


def _read(path):
    with open(path, 'rb') as stream:
        return stream.read()


def import_results(cfg, bundle_path):
    """Reject invalid returned data before modifying caches or reports."""
    cache = cfg['paths']['cache_dir']
    outdir = cfg['paths']['output_dir']
    manifest_bytes = _read(os.path.join(outdir, 'ai_analysis_bundle_manifest.json'))
    manifest = json.loads(manifest_bytes)
    input_bytes = _read(os.path.join(outdir, 'ai_analysis_input_schema.json'))
    output_bytes = _read(os.path.join(outdir, 'ai_analysis_result_schema.json'))
    prompt_bytes = _read(os.path.join(outdir, 'ai_analysis_prompt.md'))
    if (manifest['input_schema_checksum'] != digest(input_bytes)
            or manifest['output_schema_checksum'] != digest(output_bytes)
            or manifest['prompt_checksum'] != digest(prompt_bytes)):
        raise ValueError('Local AI contract checksum mismatch')
    schema = json.loads(output_bytes)
    expected = set(manifest['chunks'])
    merged = {}
    with zipfile.ZipFile(bundle_path) as bundle:
        names = bundle.namelist()
        valid_names = ({'ai_analysis_bundle_manifest.json'}
                       | {'ai_analysis_input/' + n for n in expected}
                       | {'results/' + n for n in expected})
        if len(names) != len(set(names)) or set(names) - valid_names:
            raise ValueError('Unknown or duplicate bundle member')
        if bundle.read('ai_analysis_bundle_manifest.json') != manifest_bytes:
            raise ValueError('Returned bundle belongs to another AI run')
        if not expected.issubset({n[len('ai_analysis_input/'):] for n in names
                                  if n.startswith('ai_analysis_input/')}):
            raise ValueError('Missing source chunks in result bundle')
        for name in sorted(expected):
            local = _read(os.path.join(outdir, 'ai_analysis_input', name))
            remote = bundle.read('ai_analysis_input/' + name)
            if local != remote or digest(local) != manifest['chunks'][name]:
                raise ValueError('Returned source chunk checksum mismatch')
            chunk = json.loads(local)
            validate_chunk(chunk, manifest['input_schema_checksum'],
                           manifest['output_schema_checksum'], manifest['run_id'], name)
            result_path = 'results/' + name
            if result_path not in names:
                continue
            result = json.loads(bundle.read(result_path))
            validate_result(result, chunk, schema, digest(local))
            overlap = set(merged).intersection(result['results'])
            if overlap:
                raise ValueError('Duplicate result SHA across chunks')
            merged.update(result['results'])
    prefilter = load_json(os.path.join(cache, CACHE_FILES['prefilter_kept']))
    if not isinstance(prefilter, list):
        raise ValueError('Missing prefilter cache')
    if not set(merged).issubset({commit['commit'] for commit in prefilter}):
        raise ValueError('AI result not found in local source cache')
    dest = os.path.join(outdir, 'ai_analysis_results.json')
    save_json(dest, {'run_id': manifest['run_id'], 'results': merged})
    from lib.stages.st07_ai_report import run as report_run
    report_run(cfg, cache, outdir)
    return {'run_id': manifest['run_id'], 'analyzed_commits': len(merged)}


def cmd_ai_import(args):
    cfg = load_cfg(args)
    result = import_results(cfg, args.results_bundle)
    print('AI results imported: {} commit(s), run {}'.format(
        result['analyzed_commits'], result['run_id']))
