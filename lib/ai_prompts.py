"""Collect flat Markdown prompt snapshots, resolving source symlinks once."""
from pathlib import Path
import re

ROLE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]*')


def read_prompts(directory):
    """Return sorted filename-to-bytes snapshots; never return symlinks or write outputs."""
    try:
        root = Path(directory).resolve(strict=True)
        if not root.is_dir():
            raise ValueError('Prompt path is not a directory')
        entries = sorted(root.glob('*.md'), key=lambda path: path.name)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f'Cannot read prompt directory: {directory}') from exc
    if not entries:
        raise ValueError(f'Prompt directory contains no *.md files: {directory}')
    prompts = {}
    for entry in entries:
        if not ROLE.fullmatch(entry.stem):
            raise ValueError(f'Invalid prompt role filename: {entry.name}')
        try:
            target = entry.resolve(strict=True)
            if not target.is_file():
                raise ValueError(f'Prompt target is not a regular file: {entry.name}')
            data = target.read_bytes()
            text = data.decode('utf-8')
        except (OSError, RuntimeError, UnicodeError) as exc:
            raise ValueError(f'Cannot read prompt as UTF-8 Markdown: {entry.name}') from exc
        if not text.lstrip('\ufeff').strip():
            raise ValueError(f'Prompt is empty: {entry.name}')
        prompts[entry.name] = data
    return prompts
