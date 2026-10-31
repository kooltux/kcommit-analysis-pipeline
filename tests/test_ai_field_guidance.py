"""Field semantics and output size limits stay consistent across the role schemas."""
import json
from pathlib import Path
import re

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1] / 'configs/ai'


def schema(name):
    return json.loads((ROOT / 'schemas' / (name + '.json')).read_text(encoding='utf-8'))


def without_descriptions(value):
    if isinstance(value, dict):
        return {k: without_descriptions(v) for k, v in value.items() if k != 'description'}
    if isinstance(value, list):
        return [without_descriptions(v) for v in value]
    return value


@pytest.mark.parametrize('role', ['analyst', 'cve', 'reviewer'])
def test_role_fields_match_final_definitions(role):
    final = schema('result')['$defs']['assessment']['properties']
    fields = schema(role)['$defs']['assessment']['properties']
    for name, definition in fields.items():
        assert definition.get('description', '').strip(), name
        assert definition == final[name], name


def test_assessment_field_constraints_match_output_limits():
    fields = without_descriptions(schema('result')['$defs']['assessment']['properties'])
    expected = {name: {'type': 'boolean'} for name in (
        'ai_is_security_fix', 'ai_is_bug_fix', 'ai_is_performance_enhancement',
        'ai_is_new_feature', 'ai_is_new_security_feature')}
    expected.update({name: {'type': 'string', 'maxLength': limit} for name, limit in (
        ('ai_categorisation_rationale', 600), ('ai_impact_description', 450),
        ('ai_backport_effort_reason', 250), ('ai_summary', 450))})
    for name, values in (
        ('ai_impact_on_product', ['critical', 'high', 'medium', 'low', 'none']),
        ('ai_backport_effort', ['very_easy', 'easy', 'moderate', 'hard', 'very_hard']),
        ('ai_backport_recommendation', ['strong_yes', 'yes', 'maybe', 'no', 'strong_no']),
        ('rv_agreement', ['agree', 'disagree'])):
        expected[name] = {'type': 'string', 'enum': values}
    expected['ai_risks_if_not_backported'] = {
        'type': 'array', 'uniqueItems': True, 'items': {'type': 'string', 'enum': [
            'security_vulnerability', 'system_stability', 'data_corruption',
            'performance_degradation', 'missing_feature', 'compliance_violation', 'none']}}
    expected['ai_cve_ids'] = {'type': 'array', 'maxItems': 10, 'items': {
        'type': 'string', 'pattern': '^CVE-[0-9]{4}-[0-9]{4,}$'}}
    expected['ai_cve_probabilities'] = {'type': 'array', 'maxItems': 10, 'items': {
        'type': 'integer', 'minimum': 0, 'maximum': 100}}
    names = '|'.join(name for name in fields if name.startswith('ai_'))
    patterns = {
        'rv_notes': r'^(?:' + names + r'): \[(?:minor|moderate|strong|complete)\] - [ -~]+ -> [ -~]+ \([ -~]+\)(?![\s\S])',
        'rv_recommendation': r'^(?:' + names + r'): use [ -~]+(?![\s\S])'}
    for name, pattern in patterns.items():
        expected[name] = {'type': ['array', 'null'], 'minItems': 1, 'maxItems': 15,
                          'uniqueItems': True, 'items': {
                              'type': 'string', 'maxLength': 1500 if name == 'rv_notes' else 700,
                              'pattern': pattern}}
    assert fields == expected


@pytest.mark.parametrize('role', ['analyst', 'cve', 'reviewer', 'result'])
def test_description_annotations_do_not_change_validation_keywords(role):
    document = schema(role)
    Draft202012Validator.check_schema(document)
    stripped = without_descriptions(document)
    Draft202012Validator.check_schema(stripped)
    assert document['$defs']['assessment']['required'] == list(
        document['$defs']['assessment']['properties'])
    assert not document['$defs']['assessment']['additionalProperties']


LEGACY_PROMPT_MARKER = re.compile(
    r'(?i:Qualcomm|MediaTek|Broadcom|NVIDIA|Google Drive|extracted_Filename|ai_cve_id_pattern)'
    r'|\b(?:EMPTY|PENDING)\b|\{\{#')


@pytest.mark.parametrize('text,rejected', [
    ('empty arrays', False), ('nonempty', False), ('pending review', False),
    ('not EMPTY', True), ('write PENDING', True), ('"EMPTY"', True),
    ('"PENDING"', True), ('NONEMPTY', False), ('qualcomm', True),
    ('MEDIATEK', True), ('Broadcom', True), ('nvidia', True),
    ('google drive', True), ('extracted_Filename', True),
    ('AI_CVE_ID_PATTERN', True), ('{{#loop.current#}}', True),
])
def test_legacy_prompt_marker_distinguishes_prose_from_placeholders(text, rejected):
    assert bool(LEGACY_PROMPT_MARKER.search(text)) is rejected


@pytest.mark.parametrize('role', ['analyst', 'cve', 'reviewer', 'assembler'])
def test_refinements_remain_generic_and_schema_driven(role):
    text = (ROOT / 'prompts' / (role + '.md')).read_text(encoding='utf-8')
    assert not LEGACY_PROMPT_MARKER.search(text)
    assert 'description' in text.lower()


@pytest.mark.parametrize('role', ['analyst', 'reviewer'])
def test_explicit_evidence_hints_and_generic_hardening(role):
    text = (ROOT / 'prompts' / (role + '.md')).read_text(encoding='utf-8')
    for name in ('meta.has_cve', 'meta.is_fix', 'meta.has_stable_cc',
                 'SELinux Enforcing', 'seccomp allow-list', 'capability',
                 'compile-time hardening'):
        assert name in text


def test_legacy_recommendation_scenarios_are_qualified():
    text = (ROOT / 'prompts/analyst.md').read_text(encoding='utf-8')
    section = text.split('Illustrative recommendation scenarios,', 1)[1].split(
        '## Intermediate output', 1)[0]
    assert len(re.findall(r'^- ', section, re.M)) == 6
    for value in ('strong_yes', 'yes', 'maybe', 'no', 'strong_no'):
        assert 'favor ' + value in section
    assert 'not automatic rules' in section
    assert 'breaking change requires an evidenced compatibility-risk assessment' in section


@pytest.mark.parametrize('role', ['analyst', 'result'])
def test_effort_reason_word_limit_has_hard_character_cap(role):
    field = schema(role)['$defs']['assessment']['properties']['ai_backport_effort_reason']
    assert 'at most 20 words' in field['description']
    assert 'Fixes:' in field['description'] and 'Depends-on:' in field['description']
    assert without_descriptions(field) == {'type': 'string', 'maxLength': 250}


def test_cve_record_examples_do_not_expand_candidate_policy():
    text = (ROOT / 'prompts/cve.md').read_text(encoding='utf-8')
    assert 'NVD and MITRE/CVE records' in text
    assert 'source-message-only policy' in text
    assert 'Search results cannot introduce IDs absent from the source commit message' in text
