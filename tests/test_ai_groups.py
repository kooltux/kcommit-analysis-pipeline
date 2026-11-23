"""AI group limits, query parsing and durable source-bound definitions."""
import copy
import pytest
from lib.ai_planning import GroupPlanner


class Source:
    def __init__(self, count=5):
        self.records = {format(i, '040x'): {'commit': format(i, '040x'),
                        'product_evidence': ['target'], 'body': 'evidence'}
                        for i in range(count)}

    def select(self, shas):
        if (not isinstance(shas, list) or len(set(shas)) != len(shas)
                or not set(shas) <= self.records.keys()):
            raise ValueError('Invalid source selection')
        return sorted(shas)

    def record(self, sha):
        return copy.deepcopy(self.records[sha])


def test_cap_is_stable_prefix_and_reports_incomplete_coverage(tmp_path):
    planner = GroupPlanner(Source(), 'a' * 64, tmp_path)
    complete = planner.plan({'max_commits_per_group': 2})
    capped = planner.plan({'max_commits_per_group': 2, 'max_groups': 1})
    assert complete['total_groups'] == complete['returned_groups'] == 3
    assert not complete['limited']
    assert capped['groups'] == complete['groups'][:1]
    assert capped['limited'] and capped['total_groups'] == 3
    assert capped['returned_groups'] == 1
    assert capped['plan_id'] != complete['plan_id']
    shas = [item['commit'] for group in complete['groups']
            for item in planner.group(group['group_id'])['commits']]
    assert len(shas) == len(set(shas)) == 5


def test_groups_survive_restart_and_cache_eviction(tmp_path):
    planner = GroupPlanner(Source(), 'a' * 64, tmp_path, {'cache_entries': 1})
    first = planner.plan({'max_commits_per_group': 1})['groups'][0]['group_id']
    original = planner.group(first)
    planner.plan({'max_commits_per_group': 3})
    restarted = GroupPlanner(Source(), 'a' * 64, tmp_path)
    assert restarted.group(first) == original
    assert original['commits'][0]['product_evidence'] == ['target']
    assert original['commits'][0]['body'] == 'evidence'
    with pytest.raises(KeyError):
        GroupPlanner(Source(), 'b' * 64, tmp_path).group(first)


def test_empty_input_and_oversized_commit(tmp_path):
    assert GroupPlanner(Source(0), 'a' * 64, tmp_path).plan()['groups'] == []
    with pytest.raises(ValueError, match='exceeds'):
        GroupPlanner(Source(), 'a' * 64, tmp_path).plan({'max_bytes_per_group': 1})


@pytest.mark.parametrize('query', ['max_groups=-1',
    'max_groups=1&max_groups=2', 'max_commits=1', 'max_bytes=2', 'unknown=1',
    'max_groups=true', 'max_groups=1.0', 'max_groups', 'max_groups=+1',
    'max_groups=&max_groups=0'])
def test_bad_queries(query):
    with pytest.raises(ValueError):
        GroupPlanner.query_options(query)


@pytest.mark.parametrize('name', ['max_commits_per_group', 'max_bytes_per_group', 'max_groups'])
@pytest.mark.parametrize('value', ['', '0'])
def test_empty_and_zero_queries_use_defaults(tmp_path, name, value):
    options = GroupPlanner.query_options(name + '=' + value)
    assert options == {name: 0}
    planner = GroupPlanner(Source(26), 'a' * 64, tmp_path)
    expected = planner.plan()
    assert expected['parameters'] == dict(max_commits_per_group=25,
                                        max_bytes_per_group=262144, max_groups=None)
    assert expected['total_groups'] == expected['returned_groups'] == 2
    assert not expected['limited']
    assert planner.plan(options) == expected


def test_valid_queries_and_defaults():
    assert GroupPlanner.query_options('') == {}
    assert GroupPlanner.query_options('max_commits_per_group=2&max_bytes_per_group=4096&max_groups=1') == {
        'max_commits_per_group': 2, 'max_bytes_per_group': 4096, 'max_groups': 1}


@pytest.mark.parametrize('group_id', ['../escape', 'a' * 63, 'f' * 64])
def test_unknown_groups_never_escape_store(tmp_path, group_id):
    with pytest.raises(KeyError):
        GroupPlanner(Source(), 'a' * 64, tmp_path).group(group_id)


def test_tampered_membership_fails_closed(tmp_path):
    planner = GroupPlanner(Source(), 'a' * 64, tmp_path)
    group_id = planner.plan()['groups'][0]['group_id']
    (planner.group_directory / (group_id + '.json')).write_text('{}')
    with pytest.raises(ValueError, match='persisted'):
        planner.group(group_id)
