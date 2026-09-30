"""Cross-field validation invariants for AI analysis results."""
import copy
import json
from pathlib import Path

import pytest

from lib.ai_contract import digest, encode, input_schema, project_commit, validate_result

SCHEMA = json.loads((Path(__file__).resolve().parents[1] /
                     'configs/ai/ai_analysis_result_schema.json').read_text(encoding='utf-8'))
SHA = 'a' * 40

def sample():
    record = {
        'ai_is_security_fix': False, 'ai_is_bug_fix': True,
        'ai_is_performance_enhancement': False, 'ai_is_new_feature': False,
        'ai_is_new_security_feature': False, 'ai_categorisation_rationale': 'Bug fix',
        'ai_risks_if_not_backported': ['none'], 'ai_impact_on_product': 'low',
        'ai_impact_description': 'Impact uncertain', 'ai_backport_effort': 'moderate',
        'ai_backport_effort_reason': 'Dependencies unclear', 'ai_cve_ids': [],
        'ai_cve_probabilities': [], 'ai_backport_recommendation': 'maybe',
        'ai_summary': 'Review manually',
    }
    chunk = {
        'run_id': 'b' * 64, 'source_chunk': '1.json',
        'input_schema_checksum': digest(encode(input_schema())),
        'output_schema_checksum': 'c' * 64, 'total_commits': 1,
        'commits': [project_commit({'commit': SHA, 'subject': 'fix'}, {})],
    }
    result = {
        'schema_version': '1.0', 'run_id': chunk['run_id'],
        'source_chunk': chunk['source_chunk'], 'input_checksum': 'd' * 64,
        'input_schema_checksum': chunk['input_schema_checksum'],
        'output_schema_checksum': chunk['output_schema_checksum'],
        'total_commits': 1, 'analyzed_commits': 1, 'analysis_status': 'complete',
        'results': {SHA: record},
    }
    return chunk, result

def test_valid_complete_result():
    chunk, result = sample()
    assert validate_result(result, chunk, SCHEMA, 'd' * 64)

def test_partial_can_omit_commit():
    chunk, result = sample()
    result['results'] = {}
    result['analyzed_commits'] = 0
    result['analysis_status'] = 'partial'
    assert validate_result(result, chunk, SCHEMA, 'd' * 64)

@pytest.mark.parametrize('field,value', [
    ('ai_cve_ids', ['CVE-2026-1234']),
    ('ai_cve_probabilities', [50]),
    ('ai_risks_if_not_backported', ['none', 'system_stability']),
    ('ai_risks_if_not_backported', ['none', 'none']),
])
def test_inconsistent_fields_rejected(field, value):
    chunk, result = sample()
    result['results'][SHA][field] = value
    with pytest.raises(ValueError):
        validate_result(result, chunk, SCHEMA, 'd' * 64)
