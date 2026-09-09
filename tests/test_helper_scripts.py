"""Tests for lib.stages.st07_report._copy_helper_scripts (v19.8.0).

Verifies that json_query.sh and archive_output.sh are copied into
output/scripts/ (not the output/ root), are made executable, that the
returned paths are relative to outdir (never absolute, so they stay
consistent with the other report_stats['generated_files'] entries), and
that missing source scripts are handled gracefully (warning only, no
crash).
"""
import os
import stat

from lib.stages.st07_report import _copy_helper_scripts


def _cfg_with_assets_dir(assets_dir):
    return {'paths': {'assets_dir': assets_dir}}


def test_copy_helper_scripts_creates_scripts_subdir(tmp_path):
    """Scripts are copied into <outdir>/scripts/, not <outdir>/ directly."""
    assets_dir = tmp_path / 'assets'
    assets_dir.mkdir()
    (assets_dir / 'json_query.sh').write_text('#!/bin/bash\necho query\n')
    (assets_dir / 'archive_output.sh').write_text('#!/bin/bash\necho archive\n')

    outdir = tmp_path / 'output'
    outdir.mkdir()

    cfg = _cfg_with_assets_dir(str(assets_dir))
    written = _copy_helper_scripts(cfg, str(outdir))

    scripts_dir = outdir / 'scripts'
    assert scripts_dir.is_dir()
    assert (scripts_dir / 'json_query.sh').exists()
    assert (scripts_dir / 'archive_output.sh').exists()

    # Nothing should have been dropped in outdir root
    assert not (outdir / 'json_query.sh').exists()
    assert not (outdir / 'archive_output.sh').exists()

    # Returned paths are relative to outdir, never absolute: absolute paths
    # would leak the environment into report_stats['generated_files'].
    assert sorted(written) == [
        os.path.join('scripts', 'archive_output.sh'),
        os.path.join('scripts', 'json_query.sh'),
    ]
    assert not any(os.path.isabs(p) for p in written)


def test_copy_helper_scripts_are_executable(tmp_path):
    """Copied scripts get 0o755 permissions."""
    assets_dir = tmp_path / 'assets'
    assets_dir.mkdir()
    (assets_dir / 'json_query.sh').write_text('#!/bin/bash\necho query\n')
    (assets_dir / 'archive_output.sh').write_text('#!/bin/bash\necho archive\n')

    outdir = tmp_path / 'output'
    outdir.mkdir()

    cfg = _cfg_with_assets_dir(str(assets_dir))
    _copy_helper_scripts(cfg, str(outdir))

    for name in ('json_query.sh', 'archive_output.sh'):
        path = outdir / 'scripts' / name
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode & stat.S_IXUSR, f'{name} should be user-executable'


def test_copy_helper_scripts_missing_source_is_graceful(tmp_path):
    """Missing source scripts are skipped with a warning, not an exception."""
    assets_dir = tmp_path / 'empty_assets'
    assets_dir.mkdir()  # no scripts inside

    outdir = tmp_path / 'output'
    outdir.mkdir()

    cfg = _cfg_with_assets_dir(str(assets_dir))
    written = _copy_helper_scripts(cfg, str(outdir))

    assert written == []
    # scripts/ dir should not be created if nothing was copied into it
    assert not (outdir / 'scripts').exists()


def test_copy_helper_scripts_partial_missing(tmp_path):
    """One script present, one missing: only the present one is copied."""
    assets_dir = tmp_path / 'assets'
    assets_dir.mkdir()
    (assets_dir / 'json_query.sh').write_text('#!/bin/bash\necho query\n')
    # archive_output.sh intentionally absent

    outdir = tmp_path / 'output'
    outdir.mkdir()

    cfg = _cfg_with_assets_dir(str(assets_dir))
    written = _copy_helper_scripts(cfg, str(outdir))

    assert written == [os.path.join('scripts', 'json_query.sh')]
    assert not any(os.path.isabs(p) for p in written)
    assert (outdir / 'scripts' / 'json_query.sh').exists()
    assert not (outdir / 'scripts' / 'archive_output.sh').exists()


def test_copy_helper_scripts_falls_back_to_repo_assets_dir(tmp_path):
    """When cfg has no assets_dir, real configs/assets/ scripts are used."""
    outdir = tmp_path / 'output'
    outdir.mkdir()

    cfg = {'paths': {}}
    written = _copy_helper_scripts(cfg, str(outdir))

    # The real repo ships both scripts in configs/assets/
    assert sorted(written) == [
        os.path.join('scripts', 'archive_output.sh'),
        os.path.join('scripts', 'json_query.sh'),
    ]
    assert not any(os.path.isabs(p) for p in written)
    assert (outdir / 'scripts' / 'json_query.sh').exists()
    assert (outdir / 'scripts' / 'archive_output.sh').exists()
