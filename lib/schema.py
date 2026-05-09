"""JSON-like schema validators for pipeline cache artifacts."""

COMMIT_REQUIRED_KEYS = (
    'commit', 'subject', 'author_name', 'author_time',
)

SCORED_REQUIRED_KEYS = COMMIT_REQUIRED_KEYS + (
    'score', 'matched_profiles', 'product_evidence', 'meta', 'scoring',
)


def _is_dict_list(value):
    return isinstance(value, list) and all(isinstance(x, dict) for x in value)


def validate_commit_list(data, *, require_score=False):
    if not _is_dict_list(data):
        raise ValueError('commit list must be a list of objects')
    required = SCORED_REQUIRED_KEYS if require_score else COMMIT_REQUIRED_KEYS
    for i, item in enumerate(data):
        for key in required:
            if key not in item:
                raise ValueError('commit[{0}] missing key: {1}'.format(i, key))
        if require_score:
            if not isinstance(item.get('matched_profiles'), list):
                raise ValueError('commit[{0}].matched_profiles must be a list'.format(i))
            if not isinstance(item.get('product_evidence'), list):
                raise ValueError('commit[{0}].product_evidence must be a list'.format(i))
            if not isinstance(item.get('meta'), dict):
                raise ValueError('commit[{0}].meta must be an object'.format(i))
            if not isinstance(item.get('scoring'), dict):
                raise ValueError('commit[{0}].scoring must be an object'.format(i))
    return data


def validate_filtered_commit_list(data):
    validate_commit_list(data, require_score=False)
    for i, item in enumerate(data):
        if '_filter_reason' not in item:
            raise ValueError('commit[{0}] missing key: _filter_reason'.format(i))
    return data


def validate_scored_commit_list(data):
    return validate_commit_list(data, require_score=True)
