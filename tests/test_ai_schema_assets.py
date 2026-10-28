"""Static role schemas are closed, self-contained and consistent with source data."""
import json
from pathlib import Path
import re

import pytest
from lib.ai_contract import FIELDS, input_schema

ROOT = Path(__file__).resolve().parents[1] / 'configs' / 'ai' / 'schemas'


def load(name):
    return json.loads((ROOT / (name + '.json')).read_text(encoding='utf-8'))


def assessment(name):
    return load(name)['$defs']['assessment']


def test_static_input_preserves_existing_contract():
    value = load('input')
    assert value == input_schema()
    assert set(value['properties']['commits']['items']['required']) == set(FIELDS)


@pytest.mark.parametrize('name', ['input', 'analyst', 'cve', 'reviewer', 'result'])
def test_schemas_are_closed_and_self_contained(name):
    schema = load(name)
    assert schema['$schema'] == 'https://json-schema.org/draft/2020-12/schema'
    assert schema['type'] == 'object' and schema['additionalProperties'] is False
    assert set(schema['required']) == set(schema['properties'])
    def check(value):
        if isinstance(value, dict):
            if '$ref' in value:
                assert value['$ref'].startswith('#/$defs/')
                assert value['$ref'].split('/')[-1] in schema['$defs']
            for item in value.values():
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)
    check(schema)


def test_final_fields_are_exact_role_union_without_conflicts():
    merged = {}
    for role in ('analyst', 'cve', 'reviewer'):
        record = assessment(role)
        assert set(record['required']) == set(record['properties'])
        assert record['additionalProperties'] is False
        assert not set(merged).intersection(record['properties'])
        merged.update(record['properties'])
        assert load(role)['properties']['role']['const'] == role
    final = assessment('result')
    assert final['properties'] == merged
    assert set(final['required']) == set(merged)
    assert len(merged) == 18
    assert 'role' not in load('result')['properties']
    assert set(assessment('cve')['properties']) == {'ai_cve_ids', 'ai_cve_probabilities'}
    assert set(assessment('reviewer')['properties']) == {'rv_agreement', 'rv_notes', 'rv_recommendation'}
    assert final['allOf'] == assessment('reviewer')['allOf']


@pytest.mark.parametrize('role', ['reviewer', 'result'])
def test_review_agreement_controls_null_or_array(role):
    record = assessment(role)
    condition = record['allOf'][0]
    assert condition['if']['properties']['rv_agreement']['const'] == 'agree'
    for field in ('rv_notes', 'rv_recommendation'):
        assert condition['then']['properties'][field]['type'] == 'null'
        assert condition['else']['properties'][field]['type'] == 'array'
        assert record['properties'][field]['minItems'] == 1


@pytest.mark.parametrize('severity', ['minor', 'moderate', 'strong', 'complete'])
def test_review_notes_accept_required_ascii_format(severity):
    pattern = assessment('reviewer')['properties']['rv_notes']['items']['pattern']
    note = f'ai_impact_on_product: [{severity}] - high -> medium (source evidence)'
    assert re.search(pattern, note)


@pytest.mark.parametrize('note', [
    'unknown_field: [strong] - high -> medium (reason)',
    'ai_impact_on_product: [severe] - high -> medium (reason)',
    'ai_impact_on_product: [strong] - high -> medium (raison: \u00e9)',
    'ai_impact_on_product: [strong] - high -> medium (reason)\n',
])
def test_review_notes_reject_unknown_fields_severity_unicode_and_newlines(note):
    pattern = assessment('reviewer')['properties']['rv_notes']['items']['pattern']
    assert re.search(pattern, note) is None
