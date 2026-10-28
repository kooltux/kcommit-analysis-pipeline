"""Build a directory-contract AI package in memory before any output is replaced."""
import re

from jsonschema import Draft202012Validator

from lib.ai_assets import PROMPT_ROLES, SCHEMA_ROLES
from lib.ai_contract import SHA, digest, encode, project_commit, validate_chunk
from lib.ai_schema_validation import parse_schema


def build_package(raw, product_map, snapshots, pipeline_version, chunk_size=100, batch_size=10):
    """Consume validated exact-byte snapshots returned by load_contract().

    This function reads no resource paths and writes no files. A caller may publish
    the returned files only after this construction and validation has succeeded.
    Presentation assets and executable-server generation belong to the caller.
    """
    for name, value in (('chunk_size', chunk_size), ('batch_size', batch_size)):
        if type(value) is not int or value < 1:
            raise ValueError('ai.' + name + ' must be a positive integer')
    if not isinstance(pipeline_version, str) or not pipeline_version.strip():
        raise ValueError('Pipeline version must be a nonempty string')
    if not isinstance(raw, list) or not isinstance(product_map, dict):
        raise ValueError('Invalid AI source cache structure')
    if not isinstance(snapshots, dict):
        raise ValueError('Contract snapshots must be a filename-to-bytes mapping')
    snapshots = dict(snapshots)
    required = ({'prompts/' + role + '.md' for role in PROMPT_ROLES}
                | {'schemas/' + role + '.json' for role in SCHEMA_ROLES})
    if required - set(snapshots):
        raise ValueError('Missing contract snapshots: ' + ', '.join(sorted(required - set(snapshots))))
    for name, data in snapshots.items():
        if (not isinstance(name, str) or not re.fullmatch(
                r'(?:prompts/[A-Za-z0-9][A-Za-z0-9_-]*[.]md|schemas/[A-Za-z0-9][A-Za-z0-9_-]*[.]json)', name)
                or not isinstance(data, bytes) or not data):
            raise ValueError('Invalid contract snapshot name or bytes')
    schema_bytes = snapshots['schemas/input.json']
    output_bytes = snapshots['schemas/result.json']
    validator = Draft202012Validator(parse_schema(schema_bytes, 'selected schemas/input.json'))
    commits = []
    for record in raw:
        if not isinstance(record, dict):
            raise ValueError('Invalid source commit')
        commits.append(project_commit(record, product_map))
    shas = [item['commit'] for item in commits]
    if any(not isinstance(sha, str) or not SHA.fullmatch(sha) for sha in shas):
        raise ValueError('Invalid source commit SHA')
    if len(set(shas)) != len(shas):
        raise ValueError('Duplicate source SHA across the AI source set')
    hashes = {name: digest(data) for name, data in sorted(snapshots.items())}
    input_hash, output_hash = digest(schema_bytes), digest(output_bytes)
    run_id = digest(encode(dict(pipeline_version=pipeline_version, commits=commits,
                               contract_assets=hashes, chunk_size=chunk_size, batch_size=batch_size)))
    count = max(1, (len(commits) + chunk_size - 1) // chunk_size)
    batch_count = (count + batch_size - 1) // batch_size
    chunk_width, batch_width = max(3, len(str(count))), max(3, len(str(batch_count)))
    files, chunks, batches = {}, {}, []
    for index in range(count):
        start, end = index * chunk_size, min((index + 1) * chunk_size, len(commits))
        batch_number = index // batch_size + 1
        batch_id = 'batch_' + str(batch_number).zfill(batch_width)
        name = batch_id + '/' + str(index + 1).zfill(chunk_width) + '.json'
        if index % batch_size == 0:
            batches.append(dict(batch_id=batch_id, batch_number=batch_number, chunks=[], total_commits=0))
        batches[-1]['chunks'].append(name)
        batches[-1]['total_commits'] += end - start
        chunk = dict(schema_version='1.0', pipeline_version=pipeline_version, run_id=run_id,
                     source_chunk=name, input_schema_checksum=input_hash,
                     output_schema_checksum=output_hash, total_commits=end-start,
                     chunk_info=dict(chunk_number=index+1, total_chunks=count, start_index=start,
                                     end_index=end, batch_number=batch_number, total_batches=batch_count,
                                     chunk_in_batch=index % batch_size+1), commits=commits[start:end])
        validate_chunk(chunk, input_hash, output_hash, run_id, name)
        validator.validate(chunk)
        data = encode(chunk)
        files['ai_analysis_input/' + name] = data
        chunks[name] = digest(data)
    files.update({'ai_contract/' + name: data for name, data in snapshots.items()})
    prompt = b'# AI role prompt catalog\n\nExecute each role separately using its own schema.\n'
    for name, data in sorted(snapshots.items()):
        if name.startswith('prompts/'):
            prompt += b'\n# ' + name.encode('ascii') + b'\n' + data + b'\n'
    files.update({'ai_analysis_prompt.md': prompt, 'ai_analysis_input_schema.json': schema_bytes,
                  'ai_analysis_result_schema.json': output_bytes})
    manifest = dict(schema_version='1.0', run_id=run_id, pipeline_version=pipeline_version,
                    total_commits=len(commits), chunk_size=chunk_size, batch_size=batch_size,
                    total_chunks=count, total_batches=batch_count, batches=batches,
                    input_schema_checksum=input_hash, output_schema_checksum=output_hash,
                    prompt_checksum=digest(prompt), contract_assets=hashes, chunks=chunks)
    files['ai_analysis_bundle_manifest.json'] = encode(manifest)
    return {'manifest': manifest, 'files': files}
