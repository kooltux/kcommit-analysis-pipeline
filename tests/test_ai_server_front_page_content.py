"""Keep the shared server guide scoped to clients and the HTTP API."""
import ast
from pathlib import Path
import re


PAGE = Path(__file__).resolve().parents[1] / 'configs' / 'ai' / 'ai_server_front_page.md'


def test_front_page_is_shared_api_reference():
    text = PAGE.read_text(encoding='utf-8')
    for required in ('human reviewers', 'AI clients', 'CI jobs', '### Using this server',
                     '/schema/input', '/schema/result', '/chunks', '/result/<name>',
                     '/export', 'curl --fail-with-body', 'Content-Length',
                     'HTTP 400', 'HTTP 401', 'HTTP 404', 'HTTP 405',
                     'POST to `/result/<name>` replaces the stored result',
                     '/prompt/<name>', '/schema/<name>', 'POST /result/<name>'):
        assert required in text
    assert 'POST to validation gates checks documents without storing them.' in text
    for excluded in ('kcommit_pipeline.py', 'ai-import', 'pipeline machine',
                     'Stage 08', '## About this page', '## If you are an AI client'):
        assert excluded not in text


def test_current_client_docs_do_not_advertise_removed_api():
    root = PAGE.parents[2]
    paths = [PAGE, root / 'README.md', root / 'docs/AI_ANALYSIS.md',
             root / 'docs/CONFIGURATION.md',
             root / 'configs/ai/prompts/assembler.md']
    for path in paths:
        text = path.read_text(encoding='utf-8')
        for obsolete in ('PUT /result/', 'POST or PUT /result/', 'PUT and POST replace',
                         'GET /prompt`', '`/prompt` is a catalog', '`/README.md`',
                         '--upload-file', '/prompt/<role>'):
            assert obsolete not in text, (path, obsolete)
    assert '--data-binary @result.json' in PAGE.read_text(encoding='utf-8')


def test_front_page_explains_role_handoffs_and_validation():
    text = PAGE.read_text(encoding='utf-8')
    start = text.index('### Role workflow')
    end = text.index('### Using this server')
    workflow = text[start:end]
    for fragment in ('Analyst and CVE expert', 'Reviewer', 'Assembler',
                     '/validate/role/analyst/<name>', '/validate/role/cve/<name>',
                     '/validate/role/reviewer/<name>', '/validate/workflow/<name>',
                     'rv_*', 'full commit SHA', 'Do not apply review recommendations',
                     'partial', 'store nothing', 'does not run AI models'):
        assert fragment in workflow
    assert workflow.index('3. Reviewer') < workflow.index('4. Assembler') < workflow.index('5. POST')
    for role in ('analyst', 'cve', 'reviewer', 'result'):
        assert f'/schema/{role}' in text[text.index('### Context and task'):start]
    assert 'only Assembler returns `/schema/result`' in text
    assert 'Never POST a failure report as an assessment' in text


def test_front_page_chapters_are_ordered_and_examples_are_technical():
    text = PAGE.read_text(encoding='utf-8')
    chapters = re.findall(r'^## .+$', text, re.MULTILINE)
    assert chapters == ['## 1. For human readers', '## 2. For AI clients',
                        '## 3. For automation and testing']
    batch_start = text.index('### Batch navigation')
    assert text.count('### Batch navigation') == 1
    assert text.index(chapters[0]) < batch_start < text.index(chapters[1])
    for required in ('/batches', '/batch/<batch_id>', 'batch_002/011.json', 'source_chunk'):
        assert required in text[batch_start:text.index(chapters[1])]
    technical = text.index(chapters[2])
    assert text.index('```sh') > technical
    assert text.index('```python') > technical
    snippets = re.findall(r'```python\n(.*?)```', text, re.DOTALL)
    assert snippets
    for snippet in snippets:
        ast.parse(snippet)
