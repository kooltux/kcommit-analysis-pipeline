"""Exercise the current result contract through the runtime result validator."""
import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from lib.ai_contract import digest, result_properties, validate_result

SHA = 'a' * 40
ROOT = Path(__file__).resolve().parents[1] / 'configs' / 'ai'
NOTE = 'ai_impact_on_product: [strong] - high -> medium (evidence)'
RECOMMENDATION = 'ai_impact_on_product: use medium'


@pytest.fixture
def payload():
    data = (ROOT / 'schemas' / 'result.json').read_bytes()
    schema = json.loads(data)
    props = result_properties(schema)
    assert len(props) == 18
    assert {'rv_agreement', 'rv_notes', 'rv_recommendation'} <= set(props)
    record = {}
    for key, spec in props.items():
        kind = spec['type']
        record[key] = (None if isinstance(kind, list) else False if kind == 'boolean'
                       else [] if kind == 'array' else spec.get('enum', ['evidence'])[0])
    record['ai_risks_if_not_backported'] = ['none']
    record['rv_agreement'] = 'agree'
    chunk = dict(run_id='b' * 64, source_chunk='batch_001/001.json',
                 input_schema_checksum='c' * 64, output_schema_checksum=digest(data),
                 total_commits=1, commits=[{'commit': SHA}])
    result = dict(schema_version='1.0', input_checksum='d' * 64,
                  analyzed_commits=1, analysis_status='complete', results={SHA: record},
                  **{key: chunk[key] for key in ('run_id', 'source_chunk',
                     'input_schema_checksum', 'output_schema_checksum', 'total_commits')})
    return schema, chunk, result


def check(payload):
    schema, chunk, result = payload
    return validate_result(result, chunk, schema, 'd' * 64)


def test_valid_payload_is_unchanged(payload):
    before = copy.deepcopy(payload)
    Draft202012Validator(payload[0]).validate(payload[2])
    assert check(payload)
    assert payload == before


def test_review_disagreement(payload):
    record = payload[2]['results'][SHA]
    record.update(rv_agreement='disagree', rv_notes=[NOTE],
                  rv_recommendation=[RECOMMENDATION])
    Draft202012Validator(payload[0]).validate(payload[2])
    assert check(payload)


@pytest.mark.parametrize('agreement,field,value', [
    ('agree', 'rv_notes', [NOTE]),
    ('agree', 'rv_recommendation', [RECOMMENDATION]),
    ('agree', 'rv_notes', []),
    ('disagree', 'rv_notes', None),
    ('disagree', 'rv_recommendation', None),
    ('disagree', 'rv_notes', []),
    ('disagree', 'rv_recommendation', []),
    ('disagree', 'rv_notes', 'not an array'),
    ('disagree', 'rv_notes', [True]),
    ('disagree', 'rv_notes', [{}]),
    ('disagree', 'rv_notes', [NOTE, NOTE]),
    ('disagree', 'rv_recommendation', [RECOMMENDATION, RECOMMENDATION]),
    ('disagree', 'rv_notes', [NOTE + '\n']),
    ('disagree', 'rv_notes', [NOTE.replace('strong', 'invalid')]),
    ('disagree', 'rv_notes', [NOTE.replace('ai_impact_on_product', 'unknown_field')]),
    ('disagree', 'rv_recommendation', ['ai_summary: invalid format']),
    ('agree', 'rv_recommendation', []),
    ('disagree', 'rv_recommendation', 'not an array'),
    ('disagree', 'rv_notes', [NOTE + '\t']),
    ('disagree', 'rv_notes', [NOTE + '\u00e9']),
    ('invalid', 'rv_notes', None),
])
def test_invalid_reviews_rejected(payload, agreement, field, value):
    record = payload[2]['results'][SHA]
    record.update(rv_agreement=agreement, rv_notes=[NOTE],
                  rv_recommendation=[RECOMMENDATION])
    if agreement == 'agree':
        record.update(rv_notes=None, rv_recommendation=None)
    record[field] = value
    assert not Draft202012Validator(payload[0]).is_valid(payload[2])
    with pytest.raises(ValueError):
        check(payload)


@pytest.mark.parametrize('field,value', [
    ('ai_is_security_fix', 1),
    ('ai_risks_if_not_backported', ['none', 'security_vulnerability']),
    ('ai_cve_ids', ['CVE-2026-1234']),
    ('ai_cve_probabilities', [True]),
])
def test_existing_semantic_checks_preserved(payload, field, value):
    payload[2]['results'][SHA][field] = value
    with pytest.raises(ValueError):
        check(payload)


def test_complete_coverage_and_partial_results(payload):
    payload[2].update(results={}, analyzed_commits=0)
    with pytest.raises(ValueError, match='Incomplete'):
        check(payload)
    payload[2]['analysis_status'] = 'partial'
    assert check(payload)


def test_unknown_sha_rejected(payload):
    record = payload[2]['results'].pop(SHA)
    payload[2]['results']['e' * 40] = record
    with pytest.raises(ValueError, match='unknown SHA'):
        check(payload)
