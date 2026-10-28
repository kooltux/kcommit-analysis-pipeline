"""Source-bound role and assembly gates; only standard-library dependencies."""
from lib.ai_contract import validate_result

ROLES = ('analyst', 'cve', 'reviewer')


def validate_role(role, document, chunk, schemas, input_checksum):
    if role not in ROLES:
        raise ValueError('Unknown intermediate role')
    if not isinstance(document, dict) or document.get('role') != role:
        raise ValueError('Intermediate role identity mismatch: ' + role)
    validate_result(document, chunk, schemas[role], input_checksum)
    return True


def validate_workflow(documents, chunk, schemas, input_checksum):
    """Validate contributions and preserve their values in the assembled result.

    The caller supplies authoritative chunk bytes/checksums and packaged schemas.
    Recommendations remain advisory; this gate does not apply their corrections.
    """
    if not isinstance(documents, dict) or set(documents) != set(ROLES) | {'result'}:
        raise ValueError('Workflow requires analyst, cve, reviewer and result documents')
    for role in ROLES:
        validate_role(role, documents[role], chunk, schemas, input_checksum)
    final = documents['result']
    validate_result(final, chunk, schemas['result'], input_checksum)
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
