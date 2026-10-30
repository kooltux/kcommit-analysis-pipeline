"""Role prompts must agree with the supplied schemas and with each other."""
from pathlib import Path
import re
import pytest

ROOT = Path(__file__).resolve().parents[1] / 'configs/ai'
ROLES = ('analyst', 'cve', 'reviewer', 'assembler')
SCHEMAS = ('input', 'analyst', 'cve', 'reviewer', 'result')
INVENTED = ('likely_has_cve', 'cve_match_status', 'corrected_severity',
            'corrected_is_security_relevant', 'rejected_cve_ids')
STALE_PHRASES = ('OUTPUT SCHEMA above', 'CHUNK METADATA', 'commit message and diff',
                 'as additional fields', 'Never drop a commit', 'NEVER drop a commit',
                 'Never omit a commit')


def prompt(role):
    return (ROOT / 'prompts' / (role + '.md')).read_text(encoding='utf-8')


def schema_text():
    return '\n'.join((ROOT / 'schemas' / (name + '.json')).read_text(encoding='utf-8')
                     for name in SCHEMAS)


@pytest.mark.parametrize('role', ROLES)
def test_prompts_name_only_schema_defined_fields(role):
    schemas = schema_text()
    names = set(re.findall(r'\b(?:ai|rv)_[a-z][a-z_]*[a-z]\b', prompt(role)))
    assert names
    assert [name for name in sorted(names) if '"' + name + '"' not in schemas] == []


@pytest.mark.parametrize('role', ROLES)
def test_prompts_do_not_use_invented_fields_or_stale_wording(role):
    text = prompt(role)
    assert [name for name in INVENTED if name in text] == []
    assert [phrase for phrase in STALE_PHRASES if phrase in text] == []


@pytest.mark.parametrize('role', ROLES)
def test_prompts_require_unfenced_json_responses(role):
    text = prompt(role)
    assert 'its first character must be `{` and its last character `}`' in text
    assert 'Never wrap the document in a Markdown code fence' in text
    assert 'no Markdown code fences of any kind' in text


def test_fenced_examples_are_marked_for_readability_only():
    text = prompt('reviewer')
    assert '```json' in text and 'never fence your response' in text
    for role in ('analyst', 'cve', 'assembler'):
        assert '```' not in prompt(role).replace('`{`', '').replace('`}`', '')


def test_assembler_never_alters_specialist_values():
    text = prompt('assembler')
    assert 'unchanged' in text
    assert 'Never apply, merge or resolve review recommendations' in text
    assert not re.search(r'(?i)reviewer corrections|overrides if', text)


def test_roles_keep_cve_ownership_separate():
    assert 'Leave all CVE decisions to the CVE expert' in prompt('analyst')
    cve = prompt('cve')
    assert 'explicitly present in the source commit message' in cve
    assert 'return [] for both ai_cve_ids and ai_cve_probabilities' in cve
    assert 'record proposed corrections only in the schema-defined rv_* fields' in prompt('reviewer')


@pytest.mark.parametrize('role', ROLES)
def test_hard_rules_and_rules_blocks_stay_json_only(role):
    text = prompt(role)
    assert 'You output ONLY raw JSON' in text
    assert 'Return raw JSON only' in text or 'Response starts with { and ends with }' in text
