"""Stage modules must keep their docstring as the first statement (v19.11.1).

Regression guard: a stray import above the docstring of
lib/stages/st07_report.py turned it into a dead string literal, so
``help()`` and ``__doc__`` lost the stage description and its changelog.
"""
import ast
from pathlib import Path

import pytest

from lib.stages import st07_report

STAGES_DIR = Path(__file__).resolve().parents[1] / 'lib' / 'stages'
FILES = sorted(STAGES_DIR.glob('*.py'))


def _dead_docstring_positions(tree):
    """Indexes of bare string statements near the top that are not the docstring."""
    if ast.get_docstring(tree) is not None:
        return []
    dead = []
    for index, node in enumerate(tree.body[:5]):
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            dead.append(index)
    return dead


def test_stage_files_found():
    assert any(p.name == 'st07_report.py' for p in FILES)


@pytest.mark.parametrize('path', FILES, ids=lambda p: p.name)
def test_no_dead_module_docstring(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    assert _dead_docstring_positions(tree) == [], (
        '%s has a string literal that is not the module docstring '
        '(something is placed above it)' % path.name)


def test_st07_report_docstring_is_real():
    assert st07_report.__doc__
    assert st07_report.__doc__.startswith('Stage 07 logic')
    assert 'v19.11.1' in st07_report.__doc__


def test_detector_flags_import_above_docstring():
    tree = ast.parse('import os\n"""Not a docstring."""\nx = 1\n')
    assert _dead_docstring_positions(tree) == [1]


def test_detector_accepts_normal_docstring():
    tree = ast.parse('"""Doc."""\nimport os\n')
    assert _dead_docstring_positions(tree) == []
