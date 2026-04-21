# Small file and JSON helpers shared across the pipeline stages.
from __future__ import print_function
import io
import json
import os


def ensure_dir(path):
    # Create a directory tree only when it does not already exist.
    if path and not os.path.isdir(path):
        os.makedirs(path)


def load_json(path, default=None):
    # Return parsed JSON content, or a caller-provided default when the file is absent.
    if not os.path.exists(path):
        return default
    with io.open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    # Persist structured data with stable formatting for easy inspection.
    ensure_dir(os.path.dirname(path))
    with io.open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, sort_keys=True)
