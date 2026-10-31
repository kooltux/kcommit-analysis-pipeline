"""CSV conversion, batch identity, duplicate warnings and validation tests."""
import csv
import json

import pytest

from lib.ai_exchange import decode
from lib.commands.cmd_ai_import import import_results
from tools.ai_csv_to_results import cell_value, convert, main
from test_ai_import_sources import package, record, write_json


def row_for(source, sha):
    return dict(commit_hash=sha, **{k: 'TRUE' if v is True else 'FALSE' if v is False
                else json.dumps(v) if isinstance(v, list) else v for k, v in record(source).items()})


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_conversion_grouping_partial_and_import(package, tmp_path, capsys):
    cfg, out, source = package
    shas = list(source.by_sha)[:3]
    rows = [row_for(source, sha) for sha in shas]
    rows[0]['ai_risks_if_not_backported'] = 'none'
    rows[0]['ai_cve_ids'] = 'EMPTY'
    path = tmp_path / 'manual' / 'unrelated_batch' / 'triage_0001.json.csv'
    write_csv(path, rows)
    dest = tmp_path / 'converted'
    assert convert(cfg, [path.parent.parent], dest)['analyzed_commits'] == 3
    files = sorted(dest.rglob('*.json'))
    assert [p.relative_to(dest).as_posix() for p in files] == list(source.chunks)[:2]
    assert [decode(p.read_bytes())['analysis_status'] for p in files] == ['complete', 'partial']
    assert import_results(cfg, dest)['analyzed_commits'] == 3
    stored = decode((out / 'ai_analysis_results.json').read_bytes())
    assert set(stored['results']) == set(shas)
    stderr = capsys.readouterr().err
    assert 'Discovered 1 files' in stderr and 'Wrote chunk' in stderr
    assert '1 complete, 1 partial' in stderr and 'Done:' in stderr
    with pytest.raises(ValueError, match='already exists'):
        convert(cfg, [path], dest)


def test_csv_duplicates_first_wins(package, tmp_path, capsys):
    cfg, out, source = package
    sha = next(iter(source.by_sha))
    row = row_for(source, sha)
    folder = tmp_path / 'duplicates'
    write_csv(folder / 'a.csv', [row, row])
    write_csv(folder / 'z.csv', [dict(row, ai_summary='Changed')])
    dest = tmp_path / 'converted'
    convert(cfg, [folder / 'z.csv', folder / 'a.csv'], dest)
    import_results(cfg, dest)
    assert decode((out / 'ai_analysis_results.json').read_bytes())['results'][sha] == record(source)
    stderr = capsys.readouterr().err
    assert 'WARNING conflicting duplicate ' + sha in stderr
    assert 'ai_summary' in stderr and 'retained' in stderr and 'rejected' in stderr
    assert 'a.csv:line 2' in stderr and 'z.csv:line 2' in stderr
    assert '1 identical duplicates skipped; 1 conflicting duplicates rejected' in stderr


@pytest.mark.parametrize('problem', ['rationale', 'probabilities', 'unknown_sha', 'boolean', 'column', 'short_row', 'too_long'])
def test_invalid_csv_fails_before_output(package, tmp_path, problem):
    cfg, out, source = package
    row = row_for(source, next(iter(source.by_sha)))
    if problem == 'rationale':
        del row['ai_categorisation_rationale']
    elif problem == 'probabilities':
        row['ai_cve_ids'] = 'CVE-2017-18595'
        del row['ai_cve_probabilities']
    elif problem == 'unknown_sha':
        row['commit_hash'] = 'f' * 40
    elif problem == 'boolean':
        row['ai_is_bug_fix'] = 'maybe'
    elif problem == 'column':
        row['invented'] = 'yes'
    elif problem == 'too_long':
        row['ai_summary'] = 'x' * 451
    path, dest = tmp_path / 'bad.csv', tmp_path / 'converted'
    write_csv(path, [row])
    if problem == 'short_row':
        path.write_text('commit_hash,ai_summary\n' + row['commit_hash'] + '\n')
    with pytest.raises(ValueError):
        convert(cfg, [path], dest)
    assert not dest.exists()


def test_generated_config_and_explicit_rationale_option(package, tmp_path, capsys):
    cfg, out, source = package
    config = out / 'pipeline_config.json'
    write_json(config, {'paths': {'output_dir': '.', 'cache_dir': '../cache'}})
    row = row_for(source, next(iter(source.by_sha)))
    del row['ai_categorisation_rationale']
    row.update(extracted_Filename='/', rv_notes='EMPTY', ai_cve_id_pattern='web_search')
    row['ai_cve_ids'], row['ai_cve_probabilities'] = 'CVE-2017-18595', '[80]'
    path, dest = tmp_path / 'manual.csv', tmp_path / 'converted'
    write_csv(path, [row])
    assert main(['--config', str(config), '--output-dir', str(dest),
                 '--rationale-from-summary', str(path)]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)['files_written'] == 1
    assert 'ignoring non-contract columns' in captured.err and 'Configuration:' in captured.err
    item = next(iter(decode(next(dest.rglob('*.json')).read_bytes())['results'].values()))
    assert item['ai_categorisation_rationale'] == item['ai_summary']
    assert item['ai_cve_probabilities'] == [80]


@pytest.mark.parametrize('raw', ['yes', '1', '', 'EMPTY'])
def test_invalid_boolean_cell(raw):
    with pytest.raises(ValueError):
        cell_value(raw, {'type': 'boolean'})


@pytest.mark.parametrize('raw', ['80.5', '[true]', '[80.5]', 'web_search'])
def test_invalid_probability_cell(raw):
    with pytest.raises(ValueError):
        cell_value(raw, {'type': 'array', 'items': {'type': 'integer'}})
