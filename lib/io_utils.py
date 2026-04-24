# Small file and JSON helpers shared across the pipeline stages.
import json
import os
import re


def ensure_dir(path):
    # Create a directory tree only when it does not already exist.
    if path and not os.path.isdir(path):
        os.makedirs(path)


def load_json(path, default=None):
    # Return parsed JSON content, or a caller-provided default when the file is absent.
    if not os.path.exists(path):
        return default
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_json_with_comments(path, default=None):
    """Return parsed JSON content, stripping // and # comments."""
    if not os.path.exists(path):
        return default
    with open(path, 'r', encoding='utf-8') as f:
        raw = f.read()
    
    # Strip /* */ comments
    raw = re.sub(r'/\*.*?\*/', '', raw, flags=re.S)
    
    cleaned_lines = []
    for line in raw.splitlines():
        stripped = line.lstrip()
        if stripped.startswith('//') or stripped.startswith('#'):
            continue
        cleaned_lines.append(line)
    
    text = '\n'.join(cleaned_lines)
    if not text.strip():
        return default
    return json.loads(text)


def save_json(path, data):
    # Persist structured data with stable formatting for easy inspection.
    ensure_dir(os.path.dirname(path))
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, sort_keys=True)
