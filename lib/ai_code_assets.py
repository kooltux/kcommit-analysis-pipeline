"""Read trusted embedded Python assets as data, validating syntax without execution."""
import os

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ai_embedded')
ASSET_FILES = {'entrypoint': 'entrypoint.py.src', 'package': 'package.py.src',
               'contract_routes': 'contract_routes.py.src'}


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
