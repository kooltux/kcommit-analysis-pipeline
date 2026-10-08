"""Keep the shared server guide scoped to clients and the HTTP API."""
import ast
from pathlib import Path
import re


PAGE = Path(__file__).resolve().parents[1] / 'configs' / 'ai' / 'ai_server_front_page.md'


def test_front_page_is_shared_api_reference():
    text = PAGE.read_text(encoding='utf-8')
    for required in ('human reviewers', 'AI clients', 'CI jobs', '### Using this server',
                     '/schema/input', '/schema/output', '/chunks', '/result/<name>',
                     '/export', 'curl --fail-with-body', 'Content-Length',
                     'HTTP 400', 'HTTP 401', 'HTTP 404', 'PUT replaces'):
        assert required in text
    for excluded in ('kcommit_pipeline.py', 'ai-import', 'pipeline machine',
                     'Stage 08', '## About this page', '## If you are an AI client'):
        assert excluded not in text


def test_front_page_chapters_are_ordered_and_examples_are_technical():
    text = PAGE.read_text(encoding='utf-8')
    chapters = re.findall(r'^## .+$', text, re.MULTILINE)
    assert chapters == ['## 1. For human readers', '## 2. For AI clients',
                        '## 3. For automation and testing']
    technical = text.index(chapters[2])
    assert text.index('```sh') > technical
    assert text.index('```python') > technical
    snippets = re.findall(r'```python\n(.*?)```', text, re.DOTALL)
    assert snippets
    for snippet in snippets:
        ast.parse(snippet)
