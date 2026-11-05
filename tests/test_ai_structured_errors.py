"""Structured diagnostics carry safe context through the embedded validator."""
import json

import pytest

from lib.ai_contract import AssessmentValidationError
from test_ai_output_limits import check, record, disagree, note, recommendation
from test_ai_package_server import app, package, snapshots, workflow
from test_ai_server_runtime import request, running
from lib.ai_contract import encode


def test_string_limit_details_exclude_assessment_content():
    item = record()
    item['ai_summary'] = 's' * 451
    with pytest.raises(AssessmentValidationError) as caught:
        check(item)
    assert str(caught.value) == 'String too long: ai_summary'
    assert caught.value.details == {'commit': 'a' * 40, 'field': 'ai_summary',
                                    'limit': 450, 'actual': 451}


def test_array_item_limit_details():
    with pytest.raises(AssessmentValidationError) as caught:
        check(disagree([note(1501)], [recommendation(700)]))
    assert caught.value.details['field'] == 'rv_notes'
    assert caught.value.details['limit'] == 1500
    assert caught.value.details['actual'] == 1501


def test_role_http_error_retains_details(app, workflow):
    name, documents = workflow
    sha = next(iter(documents['analyst']['results']))
    documents['analyst']['results'][sha]['ai_summary'] = 's' * 451
    with running(app) as (port, log, errors):
        status, headers, body = request(port, '/validate/role/analyst/' + name,
                                        method='POST', body=encode(documents['analyst']))
        assert status == 400
        assert json.loads(body)['error']['details'] == {
            'role': 'analyst', 'commit': sha, 'field': 'ai_summary', 'limit': 450, 'actual': 451}
