"""Accept: text/plain negotiation applies to JSON and Markdown responses only."""
import io
import json
from email.message import Message

import pytest

from lib.ai_contract import encode
from test_ai_package_server import app, package, workflow
from test_ai_preparation import snapshots
from test_ai_server_runtime import namespace, basic, request, running

PLAIN = 'text/plain; charset=utf-8'
JSON = 'application/json'
MARKDOWN = 'text/markdown; charset=utf-8'


@pytest.mark.parametrize('header,default,plain', [
    (None, JSON, False),
    ('', JSON, False),
    ('*/*', JSON, False),
    ('text/*', MARKDOWN, False),
    ('text/plain', JSON, True),
    ('TEXT/PLAIN', JSON, True),
    ('text/plain', MARKDOWN, True),
    ('text/plain, */*', JSON, True),
    ('text/plain, application/json;q=0.5', JSON, True),
    ('application/json, text/plain;q=0.5', JSON, False),
    ('text/plain, application/json', JSON, False),
    ('text/markdown, text/plain;q=0.1', MARKDOWN, False),
    ('text/plain;q=0', JSON, False),
    ('text/plain;q=abc', JSON, False),
    ('text/plain;q=2', JSON, False),
    ('garbage;;q=x, ,', JSON, False),
    ('text/html', JSON, False),
])
def test_negotiate_prefers_plain_only_when_explicit(namespace, header, default, plain):
    assert namespace['negotiate'](header, default) == (PLAIN if plain else default)


@pytest.mark.parametrize('kind', ['application/zip', 'text/html', 'application/octet-stream'])
def test_other_types_are_never_negotiated(namespace, kind):
    assert namespace['negotiate']('text/plain', kind) == kind


def send(namespace, accept, kind=JSON, body=b'{"a": 1}'):
    handler = namespace['Handler'].__new__(namespace['Handler'])
    handler.active_route = {'response_content_type': kind}
    if accept is not None:
        handler.headers = Message()
        handler.headers['Accept'] = accept
    sent = {}
    handler.send_response = lambda code: sent.update(code=code)
    handler.send_header = lambda name, value: sent.update({name: value})
    handler.end_headers = lambda: None
    handler.wfile = io.BytesIO()
    handler.send_bytes(body)
    return sent, handler.wfile.getvalue()


@pytest.mark.parametrize('accept,expected', [(None, JSON), ('*/*', JSON), ('text/plain', PLAIN)])
def test_send_bytes_negotiates_json_without_changing_body(namespace, accept, expected):
    sent, body = send(namespace, accept)
    assert (sent['code'], sent['Content-Type'], sent['Vary']) == (200, expected, 'Accept')
    assert body == b'{"a": 1}' and sent['Content-Length'] == str(len(body))


def test_send_bytes_negotiates_markdown_and_skips_zip(namespace):
    sent, body = send(namespace, 'text/plain', MARKDOWN, b'# Guide')
    assert (sent['Content-Type'], body) == (PLAIN, b'# Guide')
    sent, body = send(namespace, 'text/plain', 'application/zip', b'PK')
    assert sent['Content-Type'] == 'application/zip' and 'Vary' not in sent and body == b'PK'


@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
def test_text_plain_accept_over_http(app, workflow, auth):
    name, documents = workflow
    with running(app, auth=auth) as (port, log, errors):
        token = basic(auth) if auth else None
        catalog = json.loads(request(port, '/api', authorization=token)[2])
        for entry in catalog['routes']:
            success = entry['responses']['200']
            negotiable = success['content_type'].split(';')[0] in (JSON, 'text/markdown')
            assert ('alternative_content_types' in success) == negotiable
            if negotiable:
                assert success['alternative_content_types'] == ['text/plain']
        for path in ('/api', '/contract', '/chunks', '/schema/input', '/', '/prompt/analyst'):
            default = request(port, path, authorization=token)
            plain = request(port, path, authorization=token, accept='text/plain')
            assert default[0] == plain[0] == 200
            assert plain[1]['Content-Type'] == PLAIN
            assert default[1]['Content-Type'] != PLAIN
            assert plain[1]['Vary'] == default[1]['Vary'] == 'Accept'
            assert plain[2] == default[2]
        response = request(port, '/validate/role/analyst/' + name, method='POST',
                           body=encode(documents['analyst']), authorization=token,
                           accept='text/plain')
        assert response[0] == 200 and response[1]['Content-Type'] == PLAIN
        assert json.loads(response[2])['status'] == 'valid'
        response = request(port, '/prompt/unknown', authorization=token, accept='text/plain')
        assert response[0] == 404 and response[1]['Content-Type'] == JSON
        assert json.loads(response[2])['error']['status'] == 404
