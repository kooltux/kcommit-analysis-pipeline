import pytest

from lib.schema import validate_commit_list, validate_filtered_commit_list, validate_scored_commit_list


def test_validate_commit_list_ok():
    data = [{'commit':'a','subject':'s','author_name':'n','author_time':0}]
    assert validate_commit_list(data) == data


def test_validate_filtered_commit_list_requires_reason():
    with pytest.raises(ValueError):
        validate_filtered_commit_list([{'commit':'a','subject':'s','author_name':'n','author_time':0}])


def test_validate_scored_commit_list_requires_scoring_fields():
    with pytest.raises(ValueError):
        validate_scored_commit_list([{'commit':'a','subject':'s','author_name':'n','author_time':0}])
