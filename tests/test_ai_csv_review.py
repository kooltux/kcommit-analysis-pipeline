"""CSV null policy and end-to-end conversion for the current result contract."""
import json
from pathlib import Path

import pytest

from lib.ai_contract import result_properties
from lib.ai_exchange import Progress, WorkPackage, decode
from lib.commands.cmd_ai_import import import_results
from lib.stages.st08_prepare_ai import run
from tools.ai_csv_to_results import cell_value, convert
from test_ai_csv_conversion import write_csv
from test_st08_prepare_ai import setup_source

NOTE = 'ai_impact_on_product: [strong] - high -> medium (evidence)'
RECOMMENDATION = 'ai_impact_on_product: use medium'


@pytest.mark.parametrize('raw,expected', [
    ('', None), (' EMPTY ', None), ('null', None), (' null ', None),
    ('[]', []), ('["note"]', ['note']), ('note', ['note']),
])
@pytest.mark.parametrize('kind', [['array', 'null'], ['null', 'array']])
def test_nullable_array_cells(raw, expected, kind):
    assert cell_value(raw, {'type': kind, 'items': {'type': 'string'}}) == expected


def test_nonnullable_arrays_and_strings_keep_literal_null():
    spec = {'type': 'array', 'items': {'type': 'string'}}
    assert cell_value('', spec) == []
    assert cell_value('EMPTY', spec) == []
    assert cell_value('null', spec) == ['null']
    assert cell_value('null', {'type': 'string'}) == 'null'
    with pytest.raises(ValueError, match='Unsupported nullable'):
        cell_value('null', {'type': ['string', 'null']})


@pytest.fixture
def csv_contract(tmp_path, monkeypatch):
    cfg, cache, out = setup_source(tmp_path, [
        {'commit': 'a' * 40}, {'commit': 'b' * 40}])
    cfg['paths']['cache_dir'] = str(cache)
    run(cfg, str(cache), str(out))
    monkeypatch.setattr('lib.stages.st07_ai_report.run', lambda *args: None)
    source = WorkPackage(cfg, Progress('test-csv'))
    props = result_properties(source.schema)
    assert len(props) == 18
    assert {'rv_agreement', 'rv_notes', 'rv_recommendation'} <= set(props)
    item = {}
    for key, spec in props.items():
        kind = spec['type']
        item[key] = (None if isinstance(kind, list) else False if kind == 'boolean'
                     else [] if kind == 'array' else spec.get('enum', ['evidence'])[0])
    item['ai_risks_if_not_backported'] = ['none']
    item['rv_agreement'] = 'agree'
    return cfg, out, source, item


def csv_row(item):
    return dict(commit_hash='a' * 40, **{
        key: json.dumps(value) if value is None or isinstance(value, (list, bool)) else value
        for key, value in item.items()})


@pytest.mark.parametrize('agreement', ['agree', 'disagree'])
def test_convert_and_import_preserve_selected_contract(csv_contract, tmp_path, agreement):
    cfg, out, source, item = csv_contract
    if agreement == 'disagree':
        item.update(rv_agreement=agreement, rv_notes=[NOTE], rv_recommendation=[RECOMMENDATION])
    row = csv_row(item)
    path, dest = tmp_path / 'manual.csv', tmp_path / 'converted'
    write_csv(path, [row])
    assert convert(cfg, [path], dest)['analyzed_commits'] == 1
    document = decode(next(dest.rglob('*.json')).read_bytes())
    assert document['analysis_status'] == 'partial'
    assert document['output_schema_checksum'] == source.manifest['output_schema_checksum']
    assert document['results']['a' * 40] == item
    assert import_results(cfg, dest)['analyzed_commits'] == 1
    assert decode((out / 'ai_analysis_results.json').read_bytes())['results']['a' * 40] == item


@pytest.mark.parametrize('problem', [
    'missing', 'empty_disagree', 'array_agree', 'bad_format',
    'missing_recommendation', 'empty_agree', 'null_disagree',
])
def test_invalid_review_csv_fails_before_output(csv_contract, tmp_path, problem):
    cfg, out, source, item = csv_contract
    row = csv_row(item)
    if problem == 'missing':
        del row['rv_notes']
    elif problem == 'missing_recommendation':
        del row['rv_recommendation']
    elif problem == 'empty_agree':
        row['rv_notes'] = '[]'
    elif problem == 'null_disagree':
        row.update(rv_agreement='disagree', rv_notes='null', rv_recommendation=RECOMMENDATION)
    elif problem == 'array_agree':
        row['rv_notes'] = json.dumps([NOTE])
    else:
        row.update(rv_agreement='disagree', rv_notes='EMPTY' if problem == 'empty_disagree'
                   else 'invalid note', rv_recommendation=RECOMMENDATION)
    path, dest = tmp_path / 'invalid.csv', tmp_path / 'converted'
    write_csv(path, [row])
    with pytest.raises(ValueError):
        convert(cfg, [path], dest)
    assert not dest.exists()
