"""Reusable assessment and contribution-set gates retain document semantics."""
import copy
import json

import pytest

from lib.ai_contract import AssessmentValidationError, digest, validate_assessment, validate_result
from lib.ai_workflow import validate_contribution_set
from test_ai_output_limits import SHA, record, load, document, chunk, note
from test_ai_package_server import package, snapshots, workflow


def test_assessment_validation_needs_no_envelope_and_does_not_mutate():
    item, schema = record(), load('result')
    original = copy.deepcopy((item, schema))
    assert validate_assessment(SHA, item, schema)
    assert (item, schema) == original


@pytest.mark.parametrize('field,value,detail', [
    ('ai_is_bug_fix', 'private assessment text', 'ai_is_bug_fix'),
    ('ai_summary', 's' * 451, 'ai_summary'),
    ('ai_cve_probabilities', [], 'ai_cve_ids'),
    ('rv_notes', [note(60)], 'rv_agreement'),
    ('ai_risks_if_not_backported', ['none', 'security_vulnerability'], 'ai_risks_if_not_backported'),
])
def test_assessment_errors_retain_safe_commit_and_field(field, value, detail):
    item = record()
    item[field] = value
    with pytest.raises(AssessmentValidationError) as caught:
        validate_assessment(SHA, item, load('result'))
    assert caught.value.details['commit'] == SHA
    assert caught.value.details['field'] == detail
    assert 'private assessment text' not in str(caught.value)
    assert 'private assessment text' not in repr(caught.value.details)


@pytest.mark.parametrize('sha', [None, [], 'private assessment text'])
def test_assessment_rejects_invalid_sha_without_echoing_it(sha):
    with pytest.raises(AssessmentValidationError) as caught:
        validate_assessment(sha, record(), load('result'))
    assert caught.value.details == {'field': 'results'}
    assert str(caught.value) == 'Invalid result SHA'


def test_document_identity_diagnostic_has_field_context():
    value = document(record())
    value['run_id'] = 'invalid'
    with pytest.raises(AssessmentValidationError) as caught:
        validate_result(value, chunk(), load('result'), 'c' * 64)
    assert caught.value.details == {'field': 'run_id'}


@pytest.mark.parametrize('include_result', [False, True])
def test_explicit_contribution_sets_preserve_shapes(package, workflow, include_result):
    name, documents = workflow
    schemas = {role: json.loads(package['files']['ai_contract/schemas/' + role + '.json'])
               for role in ('analyst', 'cve', 'reviewer', 'result')}
    data = package['files']['ai_analysis_input/' + name]
    source = json.loads(data)
    selected = copy.deepcopy(documents if include_result else
                             {role: documents[role] for role in ('analyst', 'cve', 'reviewer')})
    original = copy.deepcopy(selected)
    assert validate_contribution_set(selected, source, schemas, digest(data), include_result)
    assert selected == original
    selected['unexpected'] = {}
    with pytest.raises(AssessmentValidationError) as caught:
        validate_contribution_set(selected, source, schemas, digest(data), include_result)
    assert caught.value.details == {'field': 'documents'}
