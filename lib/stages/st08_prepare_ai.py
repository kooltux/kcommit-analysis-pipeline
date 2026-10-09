"""Optional Stage 08: prepare a portable, identity-bound AI work package."""
import json
import os
import shutil

from lib.ai_contract import digest, encode, input_schema, project_commit, validate_chunk
from lib.config import load_json
from lib.manifest import CACHE_FILES, VERSION


def run(cfg, cache, outdir=None):
    outdir = outdir or cfg['paths']['output_dir']
    ai = cfg.get('ai') or {}
    size = ai.get('chunk_size', 100)
    if type(size) is not int or size <= 0:
        raise ValueError('ai.chunk_size must be a positive integer for --ai')
    from lib.resources import resource_path
    prompt = resource_path(cfg, ai.get('prompt_path'), 'ai', 'ai_analysis_prompt.md')
    front_page = resource_path(cfg, ai.get('front_page_path'), 'ai', 'ai_server_front_page.md')
    try:
        with open(front_page, 'rb') as stream:
            front_page_bytes = stream.read()
        front_page_text = front_page_bytes.decode('utf-8')
    except (OSError, UnicodeError) as exc:
        raise ValueError('Cannot read ai.front_page_path as UTF-8 Markdown: ' + str(front_page)) from exc
    if not front_page_text.strip():
        raise ValueError('ai.front_page_path Markdown is empty')
    schema_asset = resource_path(cfg, ai.get('result_schema_path'), 'ai', 'ai_analysis_result_schema.json')
    with open(prompt, 'rb') as stream:
        prompt_bytes = stream.read()
    with open(schema_asset, 'rb') as stream:
        output_bytes = stream.read()
    if not prompt_bytes.strip():
        raise ValueError('AI prompt is empty')
    output_schema = json.loads(output_bytes)
    if output_schema.get('type') != 'object' or 'results' not in output_schema.get('properties', {}):
        raise ValueError('Invalid AI output schema asset')
    prefilter_file = os.path.join(cache, CACHE_FILES['prefilter_kept'])
    product_file = os.path.join(cache, CACHE_FILES['product_map'])
    if not os.path.isfile(prefilter_file) or not os.path.isfile(product_file):
        raise FileNotFoundError('Stage 08 requires stage 04 prefilter and stage 03 product-map caches')
    raw = load_json(prefilter_file)
    product_map = load_json(product_file)
    if not isinstance(raw, list) or not isinstance(product_map, dict):
        raise ValueError('Invalid AI source cache structure')
    commits = [project_commit(item, product_map) for item in raw]
    schema_bytes = encode(input_schema())
    input_hash = digest(schema_bytes)
    output_hash = digest(output_bytes)
    run_id = digest(encode({'pipeline_version': VERSION, 'commits': commits,
                            'input_schema_checksum': input_hash,
                            'output_schema_checksum': output_hash,
                            'prompt_checksum': digest(prompt_bytes), 'chunk_size': size}))
    count = max(1, (len(commits) + size - 1) // size)
    chunk_dir = os.path.join(outdir, 'ai_analysis_input')
    os.makedirs(outdir, exist_ok=True)
    if os.path.isdir(chunk_dir):
        shutil.rmtree(chunk_dir)
    legacy = os.path.join(outdir, 'ai_analysis_input.json')
    if os.path.isfile(legacy):
        os.remove(legacy)
    os.makedirs(chunk_dir)
    chunks = {}
    for index in range(count):
        start = index * size
        end = min(start + size, len(commits))
        name = str(index + 1).zfill(len(str(count))) + '.json'
        chunk = {'schema_version': '1.0', 'pipeline_version': VERSION,
                 'run_id': run_id, 'source_chunk': name,
                 'input_schema_checksum': input_hash,
                 'output_schema_checksum': output_hash, 'total_commits': end - start,
                 'chunk_info': {'chunk_number': index + 1, 'total_chunks': count,
                                'start_index': start, 'end_index': end},
                 'commits': commits[start:end]}
        validate_chunk(chunk, input_hash, output_hash, run_id, name)
        data = encode(chunk)
        with open(os.path.join(chunk_dir, name), 'wb') as stream:
            stream.write(data)
        chunks[name] = digest(data)
    manifest = {'schema_version': '1.0', 'run_id': run_id,
                'pipeline_version': VERSION, 'total_commits': len(commits),
                'input_schema_checksum': input_hash,
                'output_schema_checksum': output_hash,
                'prompt_checksum': digest(prompt_bytes), 'chunks': chunks}
    for name, content in (('ai_analysis_prompt.md', prompt_bytes),
                          ('ai_server_front_page.md', front_page_bytes),
                          ('ai_analysis_input_schema.json', schema_bytes),
                          ('ai_analysis_result_schema.json', output_bytes),
                          ('ai_analysis_bundle_manifest.json', encode(manifest))):
        with open(os.path.join(outdir, name), 'wb') as stream:
            stream.write(content)
    from lib.ai_serve_script_gen import generate_ai_serve_script
    generate_ai_serve_script(outdir, os.path.join(outdir, 'serve_ai.pyz'))
    return {'total_commits': len(commits), 'chunk_count': count, 'run_id': run_id}
