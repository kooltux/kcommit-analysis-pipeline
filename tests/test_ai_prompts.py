"""Prompt snapshots resolve symlinks and validate all inputs without output writes."""
from pathlib import Path
import pytest
from lib.ai_prompts import read_prompts


def test_sorted_flat_snapshots(tmp_path):
    (tmp_path / 'z.md').write_bytes(b'# Z\n')
    (tmp_path / 'analyst.md').write_bytes(b'# Analyst\n')
    (tmp_path / 'ignore.txt').write_bytes(b'ignored')
    nested = tmp_path / 'nested'
    nested.mkdir()
    (nested / 'hidden.md').write_bytes(b'not a role')
    assert read_prompts(tmp_path) == {'analyst.md': b'# Analyst\n', 'z.md': b'# Z\n'}
    assert list(read_prompts(tmp_path)) == ['analyst.md', 'z.md']


def test_directory_and_file_symlinks_are_snapshotted(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    target = tmp_path / 'different-name.txt'
    target.write_bytes(b'# Analyst\n')
    (source / 'analyst.md').symlink_to(target)
    alias = tmp_path / 'alias'
    alias.symlink_to(source, target_is_directory=True)
    snapshot = read_prompts(alias)
    target.write_bytes(b'# Changed\n')
    assert snapshot == {'analyst.md': b'# Analyst\n'}
    assert read_prompts(alias) == {'analyst.md': b'# Changed\n'}


@pytest.mark.parametrize('content', [b'', b' \n', b'\xff', b'\xef\xbb\xbf'])
def test_invalid_content_rejected(tmp_path, content):
    (tmp_path / 'analyst.md').write_bytes(content)
    with pytest.raises(ValueError, match='Prompt|prompt'):
        read_prompts(tmp_path)


@pytest.mark.parametrize('kind', ['broken', 'loop', 'directory', 'invalid_name'])
def test_invalid_entries_rejected(tmp_path, kind):
    entry = tmp_path / 'analyst.md'
    if kind == 'broken':
        entry.symlink_to(tmp_path / 'missing')
    elif kind == 'loop':
        entry.symlink_to(entry)
    elif kind == 'directory':
        entry.mkdir()
    else:
        (tmp_path / 'bad role.md').write_bytes(b'# Bad')
    with pytest.raises(ValueError):
        read_prompts(tmp_path)


@pytest.mark.parametrize('kind', ['empty', 'missing', 'file'])
def test_invalid_directories_rejected(tmp_path, kind):
    path = tmp_path
    if kind == 'missing':
        path = tmp_path / 'missing'
    elif kind == 'file':
        path = tmp_path / 'file'
        path.write_bytes(b'not a directory')
    with pytest.raises(ValueError):
        read_prompts(path)


def test_basic_role_prompts_have_separate_responsibilities():
    root = Path(__file__).resolve().parents[1] / 'configs' / 'ai' / 'prompts'
    prompts = read_prompts(root)
    assert set(prompts) == {'analyst.md', 'cve.md', 'reviewer.md', 'assembler.md'}
    analyst, cve, reviewer, assembler = [prompts[name].decode('utf-8') for name in
        ('analyst.md', 'cve.md', 'reviewer.md', 'assembler.md')]
    assert 'Do not use web search' in analyst and 'do not perform CVE matching' in analyst
    assert 'ai_cve_ids' in cve and 'ai_cve_probabilities' in cve
    assert 'source-message-only' in cve and 'JSON integers from 0 to 100' in cve
    for name in ('rv_agreement', 'rv_notes', 'rv_recommendation'):
        assert name in reviewer
    assert 'both be null' in reviewer and 'plain ASCII only' in reviewer
    assert 'Do not emit ai_* fields' in reviewer and '/schema/reviewer' in reviewer
    assert 'Do not include role, pipeline_version, chunk_info, commits or another wrapper.' in assembler
    assert 'Do not apply recommendations from rv_recommendation strings.' in assembler
    assert all('trusted server metadata' in text for text in (analyst, cve, reviewer, assembler))
