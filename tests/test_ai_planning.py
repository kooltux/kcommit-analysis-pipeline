"""Canonical identity is grouping-independent; delivery plans are deterministic and bounded."""
import copy

import pytest

from lib.ai_planning import PlanCache, planning_defaults, source_document
from lib.ai_preparation import build_package
from lib.ai_result_store import _encode
from lib.ai_source import SourceIndex
from lib.manifest import VERSION
from test_ai_package_server import snapshots


def build(snapshots, chunk_size=1, batch_size=1, product=None, planning=None):
    return build_package([{'commit': 'a' * 40}, {'commit': 'b' * 40}], product or {},
                         snapshots, VERSION, chunk_size=chunk_size, batch_size=batch_size,
                         planning=planning)


def index(package):
    return SourceIndex(package['manifest'],
        lambda name: package['files']['ai_analysis_input/' + name])


def test_regrouping_preserves_canonical_identity_and_plans(snapshots):
    first = build(snapshots)
    second = build(snapshots, chunk_size=2, batch_size=10)
    assert first['manifest']['run_id'] != second['manifest']['run_id']
    run_id = first['manifest']['analysis_id']
    assert second['manifest']['analysis_id'] == run_id
    a = PlanCache(index(first), run_id).get({'max_commits': 1})
    b = PlanCache(index(second), run_id).get({'max_commits': 1})
    assert a == b
    assert build(snapshots, product={'target': 'other'})['manifest']['analysis_id'] != run_id


def test_planning_limits_do_not_change_analysis_identity(snapshots):
    first = build(snapshots, planning={'max_commits': 1})
    second = build(snapshots, planning={'max_commits': 2})
    assert first['manifest']['analysis_id'] == second['manifest']['analysis_id']
    source = index(first)
    cache = PlanCache(source, first['manifest']['analysis_id'])
    one, two = cache.get({'max_commits': 1}), cache.get({'max_commits': 2})
    assert len(one['groups']) == 2 and len(two['groups']) == 1
    assert {sha for group in one['groups'] for sha in group['commits']} == set(source.records)
    for group in one['groups']:
        assert group['input_bytes'] == len(_encode(source_document(source, cache.run_id, group['commits'])))


def test_cache_snapshots_and_eviction_are_deterministic(snapshots):
    package = build(snapshots)
    cache = PlanCache(index(package), package['manifest']['analysis_id'], {'cache_entries': 1})
    first = cache.get({'max_commits': 1})
    original = copy.deepcopy(first)
    first['groups'].clear()
    assert cache.cached(original['plan_id']) == original
    cache.get({'max_commits': 2})
    assert cache.cached(original['plan_id']) is None
    assert cache.get({'max_commits': 1}) == original


@pytest.mark.parametrize('options', [{'max_commits': 0}, {'max_bytes': True},
                                      {'cache_entries': -1}, {'unknown': 1}])
def test_invalid_defaults_are_rejected(options):
    with pytest.raises(ValueError):
        planning_defaults(options)


def test_oversized_single_commit_is_rejected_before_package_publication(snapshots):
    with pytest.raises(ValueError, match='exceeds the plan byte limit'):
        build(snapshots, planning={'max_bytes': 1})


def test_selection_is_unique_source_bound_and_empty_safe(snapshots):
    package = build(snapshots)
    cache = PlanCache(index(package), package['manifest']['analysis_id'])
    assert cache.get({'commits': []})['groups'] == []
    for selected in (['f' * 40], ['a' * 40, 'a' * 40], 'a' * 40):
        with pytest.raises(ValueError):
            cache.get({'commits': selected})
