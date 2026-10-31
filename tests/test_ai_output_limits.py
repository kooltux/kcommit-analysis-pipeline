"""Output size limits bound every role document and are enforced by the shared validator."""
import json
from pathlib import Path

import pytest

from lib.ai_contract import validate_result
from lib.ai_workflow import validate_role

ROOT = Path(__file__).resolve().parents[1] / 'configs' / 'ai' / 'schemas'
SHA = 'a' * 40
TEXT_LIMITS = {'ai_categorisation_rationale': 600, 'ai_impact_description': 450,
               'ai_backport_effort_reason': 250, 'ai_summary': 450}
LIST_LIMITS = {'ai_cve_ids': 10, 'ai_cve_probabilities': 10, 'rv_notes': 15, 'rv_recommendation': 15}
ITEM_LIMITS = {'rv_notes': 1500, 'rv_recommendation': 700}


def load(name):
    return json.loads((ROOT / (name + '.json')).read_text(encoding='utf-8'))


def properties(name):
    return load(name)['$defs']['assessment']['properties']


def record():
    return {'ai_is_security_fix': True, 'ai_is_bug_fix': False,
            'ai_is_performance_enhancement': False, 'ai_is_new_feature': False,
            'ai_is_new_security_feature': False, 'ai_categorisation_rationale': 'x',
            'ai_risks_if_not_backported': ['security_vulnerability'],
            'ai_impact_on_product': 'high', 'ai_impact_description': 'x',
            'ai_backport_effort': 'easy', 'ai_backport_effort_reason': 'x',
            'ai_cve_ids': ['CVE-2024-1234'], 'ai_cve_probabilities': [90],
            'ai_backport_recommendation': 'yes', 'ai_summary': 'x',
            'rv_agreement': 'agree', 'rv_notes': None, 'rv_recommendation': None}


def chunk():
    return {'run_id': 'r' * 64, 'source_chunk': '1.json', 'input_schema_checksum': 'a' * 64,
            'output_schema_checksum': 'b' * 64, 'total_commits': 1, 'commits': [{'commit': SHA}]}


def document(item, role=None):
    value = {'schema_version': '1.0', 'run_id': 'r' * 64, 'source_chunk': '1.json',
             'input_checksum': 'c' * 64, 'input_schema_checksum': 'a' * 64,
             'output_schema_checksum': 'b' * 64, 'analysis_status': 'complete',
             'total_commits': 1, 'analyzed_commits': 1, 'results': {SHA: item}}
    if role:
        value['role'] = role
    return value


def check(item):
    return validate_result(document(item), chunk(), load('result'), 'c' * 64)


def note(size):
    head, tail = 'ai_summary: [minor] - a -> ', ' (r)'
    return head + 'b' * (size - len(head) - len(tail)) + tail


def recommendation(size):
    head = 'ai_summary: use '
    return head + 'b' * (size - len(head))


def disagree(notes, recommendations):
    item = record()
    item.update(rv_agreement='disagree', rv_notes=notes, rv_recommendation=recommendations)
    return item


@pytest.mark.parametrize('role', ['analyst', 'cve', 'reviewer', 'result'])
def test_limits_are_declared_where_the_field_is_defined(role):
    fields = properties(role)
    for name, limit in TEXT_LIMITS.items():
        if name in fields:
            assert fields[name]['maxLength'] == limit
            assert 'Hard limit: %d characters' % limit in fields[name]['description']
    for name, limit in LIST_LIMITS.items():
        if name in fields:
            assert fields[name]['maxItems'] == limit
    for name, limit in ITEM_LIMITS.items():
        if name in fields:
            assert fields[name]['items']['maxLength'] == limit


def test_record_within_limits_is_accepted():
    assert check(record())


@pytest.mark.parametrize('field,limit', sorted(TEXT_LIMITS.items()))
def test_text_limit_is_inclusive(field, limit):
    item = record()
    item[field] = 'x' * limit
    assert check(item)
    item[field] = 'x' * (limit + 1)
    with pytest.raises(ValueError, match='String too long: ' + field):
        check(item)


def test_cve_lists_are_capped():
    ids = ['CVE-2024-%04d' % number for number in range(11)]
    item = record()
    item.update(ai_cve_ids=ids[:10], ai_cve_probabilities=[50] * 10)
    assert check(item)
    item.update(ai_cve_ids=ids, ai_cve_probabilities=[50] * 11)
    with pytest.raises(ValueError, match='Invalid array constraints: ai_cve_ids'):
        check(item)


def test_review_entry_length_is_inclusive():
    assert check(disagree([note(1500)], [recommendation(700)]))
    with pytest.raises(ValueError, match='Array item too long: rv_notes'):
        check(disagree([note(1501)], [recommendation(700)]))
    with pytest.raises(ValueError, match='Array item too long: rv_recommendation'):
        check(disagree([note(1500)], [recommendation(701)]))


def test_review_lists_are_capped():
    notes = ['ai_summary: [minor] - a%d -> b (r)' % number for number in range(16)]
    recommendations = ['ai_summary: use v%d' % number for number in range(16)]
    assert check(disagree(notes[:15], recommendations[:15]))
    with pytest.raises(ValueError, match='Invalid array constraints: rv_notes'):
        check(disagree(notes, recommendations[:15]))
    with pytest.raises(ValueError, match='Invalid array constraints: rv_recommendation'):
        check(disagree(notes[:15], recommendations))


def test_role_gate_applies_the_same_limits():
    schemas = {name: load(name) for name in ('analyst', 'cve', 'reviewer', 'result')}
    item = {key: record()[key] for key in properties('analyst')}
    assert validate_role('analyst', document(item, 'analyst'), chunk(), schemas, 'c' * 64)
    item['ai_summary'] = 'x' * 451
    with pytest.raises(ValueError, match='String too long: ai_summary'):
        validate_role('analyst', document(item, 'analyst'), chunk(), schemas, 'c' * 64)
