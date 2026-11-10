"""Source-bound role and assembly gates; only standard-library dependencies."""
from lib.ai_contract import AssessmentValidationError, validate_result

ROLES = ('analyst', 'cve', 'reviewer')


def validate_contribution_set(documents, chunk, schemas, input_checksum, include_result=False):
    """Validate exact document-set shape and each document; coverage is checked separately."""
    if type(include_result) is not bool:
        raise AssessmentValidationError('Invalid contribution set mode', field='documents')
    expected = set(ROLES) | ({'result'} if include_result else set())
    if not isinstance(documents, dict) or set(documents) != expected:
        message = ('Workflow requires analyst, cve, reviewer and result documents' if include_result
                   else 'Assembly requires exactly analyst, cve and reviewer documents')
        raise AssessmentValidationError(message, field='documents')
    for role in ROLES:
        validate_role(role, documents[role], chunk, schemas, input_checksum)
    if include_result:
        validate_result(documents['result'], chunk, schemas['result'], input_checksum)
    return True

def assemble(documents, chunk, schemas, input_checksum):
    """Mechanically assemble validated role contributions; store nothing."""
    validate_contribution_set(documents, chunk, schemas, input_checksum)
    source = {item['commit'] for item in chunk['commits']}
    results = {}
    for sha in sorted(source):
        if not all(sha in documents[role]['results'] for role in ROLES):
            continue
        combined = {}
        for role in ROLES:
            contribution = documents[role]['results'][sha]
            if set(combined) & set(contribution):
                raise ValueError('Overlapping role fields for ' + sha)
            combined.update(contribution)
        results[sha] = combined
    final = dict(schema_version='1.0', run_id=chunk['run_id'],
                 source_chunk=chunk['source_chunk'], input_checksum=input_checksum,
                 input_schema_checksum=chunk['input_schema_checksum'],
                 output_schema_checksum=chunk['output_schema_checksum'],
                 total_commits=chunk['total_commits'], analyzed_commits=len(results),
                 analysis_status='complete' if set(results) == source else 'partial', results=results)
    validate_workflow(dict(documents, result=final), chunk, schemas, input_checksum)
    return final



def validate_role(role, document, chunk, schemas, input_checksum):
    if role not in ROLES:
        raise ValueError('Unknown intermediate role')
    if not isinstance(document, dict) or document.get('role') != role:
        raise ValueError('Intermediate role identity mismatch: ' + role)
    schema = schemas[role]
    compact_fields = {'run_id', 'source_chunk', 'role', 'results'}
    if set(schema['required']) == compact_fields:
        if set(document) != compact_fields:
            raise AssessmentValidationError('Invalid compact role envelope', role=role)
        if (document['run_id'] != chunk['run_id']
                or document['source_chunk'] != chunk['source_chunk']):
            raise AssessmentValidationError('Role source identity mismatch', role=role)
        results = document['results']
        if not isinstance(results, dict):
            raise AssessmentValidationError('Results must be keyed by full commit SHA', role=role)
        source = {item['commit'] for item in chunk['commits']}
        document = dict(schema_version='1.0', run_id=chunk['run_id'],
                        source_chunk=chunk['source_chunk'], role=role,
                        input_checksum=input_checksum,
                        input_schema_checksum=chunk['input_schema_checksum'],
                        output_schema_checksum=chunk['output_schema_checksum'],
                        total_commits=chunk['total_commits'], analyzed_commits=len(results),
                        analysis_status='complete' if set(results) == source else 'partial',
                        results=results)
        schema = dict(schema, required=list(schemas['result']['required']) + ['role'])
    try:
        validate_result(document, chunk, schema, input_checksum)
    except AssessmentValidationError as exc:
        exc.details['role'] = role
        raise
    return True


def validate_workflow(documents, chunk, schemas, input_checksum):
    """Validate contributions and preserve their values in the assembled result.

    The caller supplies authoritative chunk bytes/checksums and packaged schemas.
    Recommendations remain advisory; this gate does not apply their corrections.
    """
    validate_contribution_set(documents, chunk, schemas, input_checksum, include_result=True)
    final = documents['result']
    analyst = documents['analyst']['results']
    cve = documents['cve']['results']
    reviewer = documents['reviewer']['results']
    if not set(reviewer) <= set(analyst) & set(cve):
        raise ValueError('Reviewer coverage lacks specialist contributions')
    if not set(final['results']) <= set(reviewer):
        raise ValueError('Final coverage lacks a reviewed contribution')
    for sha, actual in final['results'].items():
        expected = {}
        for role in ROLES:
            contribution = documents[role]['results'][sha]
            if set(expected) & set(contribution):
                raise ValueError('Overlapping role fields for ' + sha)
            expected.update(contribution)
        if actual != expected:
            raise ValueError('Assembly changed validated contribution values for ' + sha)
    return True
