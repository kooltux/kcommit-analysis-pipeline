"""Prompt snapshots resolve symlinks and validate all inputs without output writes."""
from pathlib import Path
import pytest
from lib.ai_prompts import read_prompts


@pytest.mark.parametrize('role,output,inputs', [
    ('analyst', 'analyst', ('input',)),
    ('cve', 'cve', ('input',)),
    ('reviewer', 'reviewer', ('input', 'analyst', 'cve')),
    ('assembler', 'result', ('input', 'analyst', 'cve', 'reviewer')),
])
def test_role_prompts_direct_model_to_exact_output_contract(role, output, inputs):
    root = Path(__file__).resolve().parents[1] / 'configs/ai'
    text = (root / 'prompts' / (role + '.md')).read_text(encoding='utf-8')
    contract = text.split('## Output contract\n', 1)[1].split('\n\nPOST', 1)[0]
    assert 'Your response must be a single valid JSON document conforming exactly to' in contract
    assert f'`{output}.json` (`/schema/{output}`)' in contract
    assert 'supplied as an attachment or quoted after this prompt' in contract
    assert 'Return JSON only: no Markdown fences, commentary, explanations' in contract
    assert 'Do not reproduce the schema itself' in contract
    assert 'missing, unreadable or conflicting, stop and report' in contract
    assert 'Before answering, check your document against the supplied output schema' in contract
    for name in (*inputs, output):
        assert f'`{name}.json`' in contract
        assert (root / 'schemas' / (name + '.json')).is_file()
    if role != 'assembler':
        assert 'do not use `result.json` as your output schema' in contract
    else:
        assert 'without an intermediate role field' in contract


@pytest.mark.parametrize('filename,required', [
    ('analyst.md', ('prefilter-kept commits', 'not pipeline-scored', 'independently',
                    'Secure Boot', 'SELinux', 'DAC', 'seccomp', 'namespaces',
                    'locked debug', 'concise and evidence-based', 'rankings',
                    'cherry-pickability', 'Use maybe', 'not line count alone',
                    'Treat meta flags as hints', 'Use ["none"] alone')),
    ('cve.md', ('source-message-only', 'source commit message',
                'JSON integers from 0 to 100', 'return [] for both arrays')),
    ('reviewer.md', ('Secure Boot', 'SELinux', 'DAC', 'seccomp', 'namespaces',
                     'locked debug', 'line count alone', 'source rankings',
                     'Do not rewrite specialist ai_* values')),
    ('assembler.md', ('operator-selected batches, chunks and limit/offset',
                      'full source_chunk path', 'one final result per source chunk',
                      'Do not apply recommendations from rv_recommendation strings.')),
])
def test_legacy_policy_has_explicit_role_owners(filename, required):
    root = Path(__file__).resolve().parents[1] / 'configs/ai/prompts'
    text = (root / filename).read_text(encoding='utf-8')
    assert all(fragment in text for fragment in required)


@pytest.mark.parametrize('role', ['analyst', 'cve'])
def test_intermediate_validation_is_not_prohibited(role):
    root = Path(__file__).resolve().parents[1] / 'configs/ai/prompts'
    text = (root / (role + '.md')).read_text(encoding='utf-8')
    assert '/validate/role/' + role + '/<name>' in text
    assert 'Never upload this intermediate document to /result/<name>' in text
    assert 'Do not POST or PUT this' not in text


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
