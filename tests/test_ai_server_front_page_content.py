"""The readable entry guide explains two complete APIs to humans and AI clients."""
from pathlib import Path
import re
PAGE = Path(__file__).resolve().parents[1] / 'configs/ai/ai_server_front_page.md'

def test_front_page_is_shared_api_reference():
    text = PAGE.read_text()
    for fragment in ('Human reviewers', 'AI clients', 'CI jobs', '/v1/api', '/v2/api', 'route registry', 'HTTP 400', 'HTTP 401', 'HTTP 404', 'HTTP 405', 'Content-Length', 'curl --fail-with-body', '--data-binary @contributions.json'):
        assert fragment.lower() in text.lower()
    assert 'no aliases or redirects' in text
    assert 'only API-definition endpoints' in text

def test_role_handoffs_and_group_independence_are_explicit():
    text = PAGE.read_text()
    for fragment in ('Analyst and CVE expert', 'Reviewer', 'exactly `run_id`, `role`, and `results`', 'exactly the same SHAs', 'There is no fourth', 'store nothing', 'Do not apply review recommendations', 'SHA-256', 'unassessed', '/validate/workflow', '/result/<sha>', '/v2/group/<group_id>', '/v2/result/<group_id>', '/v2/result/commit/<sha>', 'max_groups', 'Pre-validation is not a prerequisite'):
        assert fragment in text
    assert 'source_chunk' not in text

def test_client_guides_do_not_direct_clients_to_global_apis():
    root = PAGE.parents[2]
    for path in (PAGE, root / 'README.md', root / 'docs/AI_ANALYSIS.md'):
        text = path.read_text()
        for stale in ('POST /result/<name>', 'GET /api/version', 'GET /context/<name>', 'GET /api`'):
            assert stale not in text
    assert re.findall('^## [123][.] .+$', PAGE.read_text(), re.M) == ['## 1. For human readers', '## 2. For AI clients', '## 3. For automation and testing']
