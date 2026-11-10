"""Read trusted embedded Python assets as data, validating syntax without execution."""
import os

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ai_embedded')
ASSET_LAYOUT = {
    'entrypoint': ('entrypoint.py.src', '__main__.py'),
    'package': ('package.py.src', 'kcap_ai_runtime/__init__.py'),
    'server': ('server.py.src', 'kcap_ai_runtime/server.py'),
    'workflow': ('workflow.py.src', 'kcap_ai_runtime/workflow.py'),
    'contract_routes': ('contract_routes.py.src', 'kcap_ai_runtime/contract_routes.py'),
    'validation': ('validation.py.src', 'kcap_ai_runtime/validation.py'),
    'prompt_body': ('prompt_body.py.src', 'kcap_ai_runtime/prompt_body.py'),
}
ASSET_FILES = {name: source for name, (source, target) in ASSET_LAYOUT.items()}


def read_embedded_source(name):
    if name not in ASSET_FILES:
        raise ValueError('Unknown embedded Python asset: ' + str(name))
    path = os.path.join(ASSET_DIR, ASSET_FILES[name])
    try:
        with open(path, 'rb') as stream:
            data = stream.read()
    except OSError as exc:
        raise ValueError('Cannot read embedded Python asset: ' + path) from exc
    try:
        text = data.decode('utf-8')
        compile(text, path, 'exec')
    except (UnicodeError, SyntaxError, ValueError) as exc:
        raise ValueError('Invalid embedded Python asset: ' + path) from exc
    return data


def read_embedded_archive():
    """Load each registered asset once, rejecting inconsistent or duplicate targets."""
    if set(ASSET_LAYOUT) != set(ASSET_FILES):
        raise ValueError('Inconsistent embedded Python asset registry')
    targets = [target for source, target in ASSET_LAYOUT.values()]
    if len(targets) != len(set(targets)):
        raise ValueError('Duplicate destination in embedded Python asset registry')
    return {target: read_embedded_source(name)
            for name, (source, target) in ASSET_LAYOUT.items()}
