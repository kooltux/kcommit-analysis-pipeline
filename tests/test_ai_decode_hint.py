"""A rejected body that contains a Markdown code fence says so; acceptance is unchanged."""
import pytest

from test_ai_package_server import app, package, workflow
from test_ai_preparation import snapshots
from test_ai_server_runtime import namespace, request, running

FENCE = b'```'
HINT = 'a Markdown code fence starts at this position, send raw JSON without fences'


@pytest.mark.parametrize('body,prefix', [
    (b'{"result": ' + FENCE + b'json\n{}\n' + FENCE + b'}', 'Expecting value: line 1 column 12 (char 11)'),
    (FENCE + b'json\n{}\n' + FENCE, 'Expecting value: line 1 column 1 (char 0)'),
    (b'{"a": 1}\n' + FENCE, 'Extra data: line 2 column 1 (char 9)'),
])
def test_fence_at_error_position_adds_hint(namespace, body, prefix):
    with pytest.raises(ValueError) as caught:
        namespace['decode_json'](body)
    assert str(caught.value) == prefix + '; ' + HINT


@pytest.mark.parametrize('body', [b'{"a": }', b'not json', b'{"a": "' + FENCE + b'"', b'{"a": 1} x'])
def test_other_errors_keep_the_original_message(namespace, body):
    with pytest.raises(ValueError) as caught:
        namespace['decode_json'](body)
    assert 'Markdown code fence' not in str(caught.value)


def test_valid_json_containing_backticks_is_still_accepted(namespace):
    assert namespace['decode_json'](b'{"a": "' + FENCE + b'json"}') == {'a': '```json'}


def test_fenced_document_is_rejected_with_hint_over_http(app, workflow):
    name, documents = workflow
    body = b'{"result": ' + FENCE + b'json\n{}\n' + FENCE + b'}'
    with running(app) as (port, log, errors):
        status, headers, data = request(port, '/validate/workflow/' + name, method='POST', body=body)
    assert status == 400 and HINT in data.decode()
