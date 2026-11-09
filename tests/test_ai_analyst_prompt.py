"""Analyst instructions preserve literal fields and evidence uncertainty safeguards."""
import json
from pathlib import Path
import re

import pytest
from jsonschema import Draft202012Validator, ValidationError

from lib.ai_prompt_body import build_prompt_body

ROOT = Path(__file__).resolve().parents[1] / 'configs' / 'ai'


def prompt():
    return (ROOT / 'prompts' / 'analyst.md').read_text(encoding='utf-8')


def test_analyst_field_list_matches_schema_and_final_checklist():
    text = prompt()
    schema = json.loads((ROOT / 'schemas' / 'analyst.json').read_bytes())
    fields = re.findall(r'^- (ai_[a-z_]+)$', text, re.MULTILINE)
    assessment = schema['$defs']['assessment']
    assert len(fields) == 13
    assert fields == assessment['required']
    assert set(fields) == set(assessment['properties'])
    mentioned = set(re.findall(r'\b(?:ai|rv)_[a-z][a-z_]*[a-z]\b', text))
    assert mentioned <= set(assessment['properties'])
    assert 'Return raw JSON only' in text
    checklist = text.split('## Final structural checklist\n', 1)[1].split('\n## ', 1)[0]
    for fragment in ('top-level keys are exactly run_id, source_chunk, role and results',
                     'exactly the 13 field names', 'never rename them',
                     'including the last one', 'missing or extra keys',
                     '"ai_is_new_feature": false', 'Never append a Boolean value to its field name',
                     '20-word limit', 'not server validation'):
        assert fragment in checklist


def test_analyst_distinguishes_unknown_from_negative_findings():
    text = ' '.join(prompt().split())
    for fragment in ('evidence that establishes its non-applicability',
                     'insufficient evidence to decide',
                     'false means the supplied evidence does not establish that classification',
                     'it does not prove the opposite',
                     'does not establish that it is disabled',
                     'missing configuration or exposure evidence as the sole reason',
                     'do not automatically replace uncertainty with high impact',
                     'Use maybe for ai_backport_recommendation'):
        assert fragment in text


def test_analyst_limits_dependency_claims_and_keeps_assembly_out_of_scope():
    text = ' '.join(prompt().split())
    assert 'no dependency is identified in the supplied evidence' in text
    assert 'State relevant target-kernel compatibility uncertainty' in text
    assert 'solely because it is small or localized' in text
    assert 'supplied source chunk and trusted product/configuration context only' in text
    assert 'assembly cannot satisfy the schema' not in text
    assert 'The external orchestrator handles validation, retries and handoffs.' in text


@pytest.mark.parametrize('extra', ['ai_is_new_feature_true', 'helper_explanation'])
def test_analyst_schema_still_rejects_invented_assessment_fields(extra):
    schema = json.loads((ROOT / 'schemas' / 'analyst.json').read_bytes())
    record = {}
    for key, spec in schema['$defs']['assessment']['properties'].items():
        kind = spec['type']
        record[key] = (False if kind == 'boolean' else [] if kind == 'array'
                       else spec.get('enum', ['evidence'])[0])
    record['ai_risks_if_not_backported'] = ['none']
    document = dict(run_id='a' * 64, source_chunk='batch_001/001.json',
                    role='analyst', results={'b' * 40: record})
    validator = Draft202012Validator(schema)
    validator.validate(document)
    record[extra] = False
    with pytest.raises(ValidationError, match='Additional properties'):
        validator.validate(document)


def test_served_analyst_body_contains_guidance_and_unchanged_schemas():
    body = build_prompt_body('analyst', lambda path: (ROOT / path).read_bytes()).decode('utf-8')
    assert body.startswith(prompt().rstrip('\n') + '\n\n## Artefacts\n')
    blocks = re.findall(r'```json\n(.*?)\n```', body, re.DOTALL)
    assert len(blocks) == 2
    for name, block in zip(('input', 'analyst'), blocks):
        assert json.loads(block) == json.loads((ROOT / 'schemas' / (name + '.json')).read_bytes())
    assert '## Final structural checklist' in body
