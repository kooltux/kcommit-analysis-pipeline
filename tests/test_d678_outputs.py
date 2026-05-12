import json
import os

from lib.html_report import generate_html_report
from lib.scoring import order_commit_details
from lib.stages import st07_report


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)


def _commit(sha='abcdef1234567890', reason=''):
    return {
        'commit': sha, 'subject': 'usb fix', 'author_name': 'Alice', 'author_email': 'alice@example.com', 'author_time': 1700000000,
        'files': ['drivers/usb/core.c'], 'product_evidence': ['config_map:CONFIG_USB'], 'matched_profiles': ['p'],
        'score': 42, '_filter_reason': reason, 'body': 'line1\nline2', 'scoring': {'profiles': {'p': 42}},
    }


def _cfg(tmp_path, reports_extra=None):
    cfg = {'paths': {'templates_dir': None}, 'reports': {'outputs': ['html'], 'top_n': 0}, 'profiles': {'active': {'p': 100}}, '_meta': {'config_dir': str(tmp_path)}}
    if reports_extra:
        cfg['reports'].update(reports_extra)
    return cfg


def test_order_commit_details_uses_git_log_like_key_order():
    ordered = order_commit_details({'body': 'b', 'subject': 's', 'commit': 'abc', 'author_time': 1, 'files': ['f'], 'score': 2})
    assert list(ordered)[:5] == ['commit', 'subject', 'author_time', 'files', 'body']


def test_generate_html_report_supports_sidecar_and_compressed_modes(tmp_path):
    tpl = tmp_path / 'tpl'; tpl.mkdir()
    (tpl / 'report.html').write_text('<html><head>__COMMITS_DATA__<style>__CSS__</style></head><body>__BODY__<script>__JS__</script></body></html>')
    (tpl / 'summary.css').write_text('')
    (tpl / 'summary.js').write_text('')
    (tpl / 'logo.svg').write_text('')
    out1 = tmp_path / 'sidecar.html'
    generate_html_report([_commit()], {}, {}, str(out1), templates_dir=str(tpl), detail_mode='sidecar', commit_index_path='./relevant_commits.table.json', commit_detail_root='./commits', metadata_path='./report_metadata.json')
    txt1 = out1.read_text()
    assert '__KC_COMMITS_INDEX__' in txt1
    assert '__KC_COMMIT_DETAIL_ROOT__' in txt1
    assert 'KCOMMIT_REPORT_METADATA_URL' in txt1
    out2 = tmp_path / 'embedded.html'
    generate_html_report([_commit()], {}, {}, str(out2), templates_dir=str(tpl), detail_mode='embedded', embed_compression='zlib')
    txt2 = out2.read_text()
    assert '__KC_COMMITS_COMPRESSED__' in txt2
    assert '__KC_COMMITS_COMPRESSION__="zlib"' in txt2


def test_stage07_writes_sidecar_tables_and_sharded_commit_details(tmp_path, monkeypatch):
    cache = tmp_path / 'cache'; out = tmp_path / 'out'
    cache.mkdir(); out.mkdir()
    _write(str(cache / 'relevant_commits.json'), [_commit()])
    _write(str(cache / 'filtered_commits.json'), [_commit('1234567890abcdef', 'path_blacklist')])
    _write(str(cache / 'postfilter_dropped_commits.json'), [])
    monkeypatch.setattr('lib.profile_rules.load_profile_rules', lambda cfg: {'p': {'description': 'Profile p'}})
    st07_report.run(_cfg(tmp_path, {'html_detail_mode': 'sidecar'}), str(cache), str(out))
    assert os.path.exists(out / 'relevant_commits.table.json')
    assert os.path.exists(out / 'filtered_commits.table.json')
    assert os.path.exists(out / 'report_metadata.json')
    assert os.path.exists(out / 'commits' / 'ab' / 'cd' / 'abcdef1234567890.json')
    data = json.load(open(out / 'relevant_commits.json'))
    assert list(data[0])[:6] == ['commit', 'subject', 'author_name', 'author_email', 'author_time', 'files']


def test_sidecar_index_contains_full_commit(tmp_path):
    import json
    from lib.stages.st07_report import run
    from lib.manifest import CACHE_FILES
    outdir = tmp_path / 'out'
    cache_dir = tmp_path / 'cache'
    cache_dir.mkdir()
    relevant = [{
        'commit': 'c'*40, 'subject': 'usb fix', 'author_name': 'Bob', 'author_email': 'b@example.com',
        'author_time': 1710000000, 'body': 'detail', 'files': ['drivers/usb/core.c'],
        'score': 9, 'matched_profiles': ['p'], 'product_evidence': [],
        'scoring': {'profiles': {'p': 9}, 'trace': {'profiles': {}}}
    }]
    (cache_dir / CACHE_FILES['relevant']).write_text(json.dumps(relevant), encoding='utf-8')
    (cache_dir / CACHE_FILES['filtered']).write_text('[]', encoding='utf-8')
    (cache_dir / CACHE_FILES['postfilter_dropped']).write_text('[]', encoding='utf-8')
    cfg = {
        'profiles': {'active': {'performance': 100}},
        'paths': {
            'profiles_dirs': [os.path.abspath('configs/profiles')],
            'rules_dirs': [os.path.abspath('configs/rules')],
        },
        'reports': {'outputs': ['html'], 'html_detail_mode': 'sidecar'},
    }
    run(cfg, str(cache_dir), str(outdir))
    idx = json.load(open(outdir / 'relevant_commits.table.json', encoding='utf-8'))
    row = idx[0]
    assert row['commit'] == 'c'*40
    assert row['subject'] == 'usb fix'
    assert 'product_evidence' not in row
