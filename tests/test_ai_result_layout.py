"""Result-record layout compatibility; payload migration is tested separately."""
import copy
import json
from pathlib import Path

import pytest

from lib.ai_contract import result_properties


def schema_with(record):
    return {'properties': {'results': {'additionalProperties': record}}}


def test_inline_layout_preserves_identity_and_schema():
    props = {'value': {'type': 'boolean'}}
    schema = schema_with({'properties': props})
    before = copy.deepcopy(schema)
    assert result_properties(schema) is props
    assert schema == before


def test_reference_chain_and_pointer_escapes():
    schema = schema_with({'$ref': '#/$defs/first'})
    schema['$defs'] = {
        'first': {'$ref': '#/$defs/a~1b~0c'},
        'a/b~c': {'type': 'object', 'properties': {'value': {'type': 'string'}}},
    }
    assert set(result_properties(schema)) == {'value'}


@pytest.mark.parametrize('record', [
    True, None, {}, {'properties': []},
    {'type': 'array', 'properties': {}},
    {'$ref': 'https://example.invalid/schema'},
    {'$ref': '#/$defs/missing'},
    {'$ref': '#/$defs/bad~2escape'},
    {'$ref': '#/$defs/loop'},
    {'$ref': '#/$defs/loop', 'properties': {}},
])
def test_invalid_layout_fails_closed(record):
    schema = schema_with(record)
    schema['$defs'] = {'loop': {'$ref': '#/$defs/loop'}}
    with pytest.raises(ValueError):
        result_properties(schema)


def test_installed_final_schema_layout():
    path = Path(__file__).resolve().parents[1] / 'configs/ai/schemas/result.json'
    schema = json.loads(path.read_text(encoding='utf-8'))
    before = copy.deepcopy(schema)
    props = result_properties(schema)
    assert len(props) == 18
    assert {'rv_agreement', 'rv_notes', 'rv_recommendation'} <= set(props)
    assert schema == before
