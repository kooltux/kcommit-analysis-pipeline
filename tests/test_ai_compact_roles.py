"""Compact role validation derives transport fields without changing final results."""
import copy
import json

import pytest

from lib.ai_contract import AssessmentValidationError
from lib.ai_workflow import assemble, validate_role, validate_workflow
from test_ai_package_server import package, snapshots, workflow


@pytest.fixture
def compact(package, workflow):
    name, documents = workflow
    chunk = json.loads(package['files']['ai_analysis_input/' + name])
    schemas = {role: json.loads(package['files']['ai_contract/schemas/' + role + '.json'])
               for role in ('analyst', 'cve', 'reviewer', 'result')}
    fields = ['run_id', 'source_chunk', 'role', 'results']
    roles = {}
    for role in ('analyst', 'cve', 'reviewer'):
        assert schemas[role]['required'] == fields
        assert set(schemas[role]['properties']) == set(fields)
        roles[role] = {key: documents[role][key] for key in fields}
    return roles, chunk, schemas, documents['result']


def test_compact_assembly_preserves_final_contract_and_inputs(compact):
    roles, chunk, schemas, expected = compact
    before = copy.deepcopy((roles, chunk, schemas))
    actual = assemble(roles, chunk, schemas, expected['input_checksum'])
    assert actual == expected
    assert validate_workflow(dict(roles, result=actual), chunk, schemas, expected['input_checksum'])
    assert (roles, chunk, schemas) == before


def test_compact_partial_and_empty_coverage(compact):
    roles, chunk, schemas, expected = compact
    roles['reviewer']['results'] = {}
    actual = assemble(roles, chunk, schemas, expected['input_checksum'])
    assert actual['analysis_status'] == 'partial'
    assert actual['analyzed_commits'] == 0 and actual['results'] == {}
    for document in roles.values():
        document['results'] = {}
    chunk.update(commits=[], total_commits=0)
    actual = assemble(roles, chunk, schemas, expected['input_checksum'])
    assert actual['analysis_status'] == 'complete'
    assert actual['total_commits'] == actual['analyzed_commits'] == 0


@pytest.mark.parametrize('field,value', [
    ('run_id', '0' * 64), ('source_chunk', 'batch_999/999.json'),
    ('role', 'cve'), ('results', []), ('input_checksum', '0' * 64)])
def test_compact_envelope_and_identity_are_strict(compact, field, value):
    roles, chunk, schemas, expected = compact
    roles['analyst'][field] = value
    with pytest.raises(ValueError):
        validate_role('analyst', roles['analyst'], chunk, schemas, expected['input_checksum'])


def test_compact_unknown_sha_and_unreviewable_coverage_are_rejected(compact):
    roles, chunk, schemas, expected = compact
    sha = next(iter(roles['analyst']['results']))
    roles['analyst']['results']['f' * 40] = roles['analyst']['results'][sha]
    with pytest.raises(ValueError, match='unknown SHA'):
        assemble(roles, chunk, schemas, expected['input_checksum'])
    del roles['analyst']['results']['f' * 40]
    roles['cve']['results'] = {}
    with pytest.raises(ValueError, match='Reviewer coverage'):
        assemble(roles, chunk, schemas, expected['input_checksum'])


def test_compact_review_proposals_are_not_applied(compact):
    roles, chunk, schemas, expected = compact
    sha = next(iter(roles['analyst']['results']))
    original = roles['analyst']['results'][sha]['ai_is_bug_fix']
    proposed = not original
    old, new = json.dumps(original), json.dumps(proposed)
    review = roles['reviewer']['results'][sha]
    review.update(rv_agreement='disagree',
                  rv_notes=[f'ai_is_bug_fix: [strong] - {old} -> {new} (source evidence)'],
                  rv_recommendation=[f'ai_is_bug_fix: use {new}'])
    actual = assemble(roles, chunk, schemas, expected['input_checksum'])
    assert actual['results'][sha]['ai_is_bug_fix'] is original
    assert actual['results'][sha]['rv_notes'] == review['rv_notes']
    assert actual['results'][sha]['rv_recommendation'] == review['rv_recommendation']


def test_compact_length_errors_retain_context(compact):
    roles, chunk, schemas, expected = compact
    sha = next(iter(roles['analyst']['results']))
    roles['analyst']['results'][sha]['ai_summary'] = 'x' * 451
    with pytest.raises(AssessmentValidationError) as caught:
        assemble(roles, chunk, schemas, expected['input_checksum'])
    assert caught.value.details == {'role': 'analyst', 'commit': sha,
                                    'field': 'ai_summary', 'limit': 450, 'actual': 451}
