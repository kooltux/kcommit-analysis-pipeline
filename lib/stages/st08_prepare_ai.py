"""Optional Stage 08: prepare a portable, identity-bound AI work package."""
import os
import shutil
import tempfile

from lib.ai_assets import load_contract
from lib.ai_preparation import build_package
from lib.ai_package_server import generate_ai_package_server
from lib.config import load_json
from lib.manifest import CACHE_FILES, VERSION
from lib.ai_schema_validation import bundled_schema_problems


def run(cfg, cache, outdir=None):
    problems = bundled_schema_problems()
    if problems:
        raise ValueError('\n'.join(problems))
    outdir = outdir or cfg['paths']['output_dir']
    ai = cfg.get('ai') or {}
    size = ai.get('chunk_size', 100)
    if type(size) is not int or size <= 0:
        raise ValueError('ai.chunk_size must be a positive integer')
    batch_size = ai.get('batch_size', 10)
    if type(batch_size) is not int or batch_size <= 0:
        raise ValueError('ai.batch_size must be a positive integer')
    from lib.resources import resource_path
    front_page = resource_path(cfg, ai.get('front_page_path'), 'ai', 'ai_server_front_page.md')
    try:
        with open(front_page, 'rb') as stream:
            front_page_bytes = stream.read()
        front_page_text = front_page_bytes.decode('utf-8')
    except (OSError, UnicodeError) as exc:
        raise ValueError('Cannot read ai.front_page_path as UTF-8 Markdown: ' + str(front_page)) from exc
    if not front_page_text.strip():
        raise ValueError('ai.front_page_path Markdown is empty')
    contract = load_contract(cfg)
    prefilter_file = os.path.join(cache, CACHE_FILES['prefilter_kept'])
    product_file = os.path.join(cache, CACHE_FILES['product_map'])
    if not os.path.isfile(prefilter_file) or not os.path.isfile(product_file):
        raise FileNotFoundError('Stage 08 requires stage 04 prefilter and stage 03 product-map caches')
    raw = load_json(prefilter_file)
    product_map = load_json(product_file)
    if not isinstance(raw, list) or not isinstance(product_map, dict):
        raise ValueError('Invalid AI source cache structure')
    package = build_package(raw, product_map, contract['files'], VERSION,
                            chunk_size=size, batch_size=batch_size)
    manifest = package['manifest']
    parent = os.path.dirname(os.path.abspath(outdir))
    os.makedirs(parent, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ai-prepare-', dir=parent) as prepared:
        # Validate and generate the whole server before replacing live assets.
        generate_ai_package_server(package, front_page_bytes,
                                   os.path.join(prepared, 'serve_ai.pyz'))
        files = dict(package['files'])
        files['ai_server_front_page.md'] = front_page_bytes
        for name, data in files.items():
            target = os.path.join(prepared, name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, 'wb') as stream:
                stream.write(data)
        os.makedirs(outdir, exist_ok=True)
        for name in ('ai_analysis_input', 'ai_contract'):
            target = os.path.join(outdir, name)
            if os.path.isdir(target) and not os.path.islink(target):
                shutil.rmtree(target)
            elif os.path.lexists(target):
                os.unlink(target)
            os.replace(os.path.join(prepared, name), target)
        for name in sorted(os.listdir(prepared)):
            os.replace(os.path.join(prepared, name), os.path.join(outdir, name))
    return {'total_commits': manifest['total_commits'],
            'chunk_count': manifest['total_chunks'],
            'batch_count': manifest['total_batches'], 'run_id': manifest['run_id']}
