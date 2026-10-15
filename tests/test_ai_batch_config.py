"""Configuration regression tests for AI chunk batching."""
import pytest

from lib.config import CONFIG_SCHEMA
from lib.stages.st08_prepare_ai import run


def test_batch_size_schema_requires_positive_integer():
    assert CONFIG_SCHEMA['ai']['batch_size'] == {'type': 'int', 'min': 1}


@pytest.mark.parametrize('value', [0, -1, True, False, None, '10', 1.5])
def test_invalid_batch_size_fails_before_output_is_created(tmp_path, value):
    output = tmp_path / 'output'
    cfg = {'paths': {'output_dir': str(output)}, 'ai': {'batch_size': value}}
    with pytest.raises(ValueError, match='ai.batch_size must be a positive integer'):
        run(cfg, str(tmp_path / 'cache'))
    assert not output.exists()



