"""Meta-schema correctness, offline references, payloads and fail-fast entry points."""
from argparse import Namespace

import pytest
from jsonschema import Draft202012Validator
from lib import ai_schema_validation as checks


@pytest.mark.parametrize('value', [True, False, {'type': 'object'},
    {'$defs': {'a/b': {'type': 'string'}}, '$ref': '#/$defs/a~1b'},
    {'$defs': {'item': {'$anchor': 'item', 'type': 'string'}}, '$ref': '#item'},
    {'const': {'$ref': 'https://example.invalid/not-a-schema'}}])
def test_valid_offline_schemas(value):
    assert checks.check_schema(value) == value


@pytest.mark.parametrize('value', [None, [], {'type': 'invented'},
    {'minimum': 'zero'}, {'required': 'field'}, {'properties': {'a': {'type': 123}}},
    {'$schema': 'https://example.invalid/draft'}, {'$ref': '#/$defs/missing'},
    {'$ref': 'https://example.invalid/schema'}, {'$dynamicRef': 'other.json'},
    {'$defs': {'x': {'$id': 'child', 'type': 'string'}}},
    {'$defs': {'x': {'$anchor': 'same'}, 'y': {'$anchor': 'same'}}}])
def test_invalid_schemas_have_origin(value):
    with pytest.raises(ValueError, match='broken.json'):
        checks.check_schema(value, 'broken.json')


@pytest.mark.parametrize('data', [b'{', b'\xff', b'{"type":"string","type":"number"}',
    b'{"const":NaN}', b'{"const":Infinity}'])
def test_strict_json(data):
    with pytest.raises(ValueError, match='bad.json'):
        checks.parse_schema(data, 'bad.json')


def test_dependency_is_required(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, 'jsonschema', None)
    with pytest.raises(ValueError, match='requirements.txt'):
        checks.check_schema({})


def test_missing_bundle_is_not_skipped(tmp_path):
    problems = checks.bundled_schema_problems(tmp_path)
    assert len(problems) == 5
    assert all(any(name + '.json' in p for p in problems) for name in checks.SCHEMA_NAMES)


def test_bundle_is_rechecked_after_change(tmp_path):
    for name in checks.SCHEMA_NAMES:
        (tmp_path / (name + '.json')).write_text('{}', encoding='utf-8')
    assert checks.bundled_schema_problems(tmp_path) == []
    (tmp_path / 'cve.json').write_text('{"type":"wrong"}', encoding='utf-8')
    assert len(checks.bundled_schema_problems(tmp_path)) == 1


@pytest.mark.parametrize('name', checks.SCHEMA_NAMES)
def test_repository_schema_is_valid(name):
    schema = checks.load_schema(checks.SCHEMA_DIR / (name + '.json'))
    assert schema['$schema'] == checks.DRAFT
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize('name', ['analyst', 'cve', 'reviewer', 'result'])
def test_repository_role_payloads(name):
    schema = checks.load_schema(checks.SCHEMA_DIR / (name + '.json'))
    record = {}
    for key, spec in schema['$defs']['assessment']['properties'].items():
        kind = spec['type']
        record[key] = (None if isinstance(kind, list) else False if kind == 'boolean'
                       else [] if kind == 'array' else spec.get('enum', ['evidence'])[0])
    if 'rv_agreement' in record:
        record['rv_agreement'] = 'agree'
    if 'ai_risks_if_not_backported' in record:
        record['ai_risks_if_not_backported'] = ['none']
    value = dict(schema_version='1.0', run_id='a' * 64, source_chunk='batch_001/001.json',
                 input_checksum='b' * 64, input_schema_checksum='c' * 64,
                 output_schema_checksum='d' * 64, analysis_status='complete',
                 total_commits=1, analyzed_commits=1, results={'a' * 40: record})
    if name != 'result':
        value['role'] = name
    validator = Draft202012Validator(schema)
    validator.validate(value)
    value['unexpected'] = True
    assert not validator.is_valid(value)
    del value['unexpected']
    if name in ('reviewer', 'result'):
        record.update(rv_agreement='disagree', rv_notes=None, rv_recommendation=None)
        assert not validator.is_valid(value)
        record.update(rv_notes=['ai_impact_on_product: [strong] - high -> medium (evidence)'],
                      rv_recommendation=['ai_impact_on_product: use medium'])
        validator.validate(value)
        record['rv_notes'][0] += '\n'
        assert not validator.is_valid(value)


def test_repository_input_payload():
    from lib.ai_contract import project_commit
    schema = checks.load_schema(checks.SCHEMA_DIR / 'input.json')
    value = dict(schema_version='1.0', pipeline_version='test', run_id='a' * 64,
                 source_chunk='001.json', input_schema_checksum='b' * 64,
                 output_schema_checksum='c' * 64, total_commits=1,
                 chunk_info=dict(chunk_number=1, total_chunks=1, start_index=0, end_index=1),
                 commits=[project_commit({'commit': 'a' * 40}, {})])
    validator = Draft202012Validator(schema)
    validator.validate(value)
    value['commits'][0]['author_time'] = 'wrong'
    assert not validator.is_valid(value)


def test_legacy_content_checker_validates_schema(tmp_path):
    from lib.content_checks import check_ai_result_schema
    path = tmp_path / 'legacy.json'
    path.write_text('{"type":"object","properties":{"results":{"type":"wrong"}}}', encoding='utf-8')
    assert 'invalid JSON Schema' in check_ai_result_schema(path)


@pytest.mark.parametrize('entry', ['validate_inputs', 'validate_config_only', 'command', 'prepare'])
def test_runtime_entry_points_fail_before_downstream_work(tmp_path, monkeypatch, entry):
    from lib import validation
    monkeypatch.setattr(checks, 'SCHEMA_DIR', tmp_path / 'missing-schemas')
    cfg = {'paths': {'work_dir': str(tmp_path / 'work')},
           'kernel': {'rev_old': 'a', 'rev_new': 'b'}}
    if entry in ('validate_inputs', 'validate_config_only'):
        problems, _ = getattr(validation, entry)(cfg)
        assert any('input.json' in p and 'cannot read schema' in p for p in problems)
    elif entry == 'command':
        import importlib
        cmd_validate = importlib.import_module('lib.commands.cmd_validate')
        monkeypatch.setattr(cmd_validate, 'load_cfg', lambda args: cfg)
        with pytest.raises(SystemExit) as error:
            cmd_validate.cmd_validate(Namespace(config='test.json'))
        assert error.value.code == 1
    else:
        from lib.stages import st00_prepare
        monkeypatch.setattr(st00_prepare, 'update_stage_progress', lambda *args: None)

        def forbidden(*args, **kwargs):
            pytest.fail('rule compilation must not run with invalid schemas')
        monkeypatch.setattr(st00_prepare, 'compile_rules_for_config', forbidden)
        with pytest.raises(SystemExit) as error:
            st00_prepare.run(cfg, str(tmp_path))
        assert error.value.code == 2


def test_independent_ai_prepare_rejects_before_writes(tmp_path, monkeypatch):
    from lib.stages import st08_prepare_ai
    monkeypatch.setattr(checks, 'SCHEMA_DIR', tmp_path / 'missing-schemas')
    out = tmp_path / 'output'
    with pytest.raises(ValueError, match='input.json'):
        st08_prepare_ai.run({}, str(tmp_path), str(out))
    assert not out.exists()


@pytest.mark.parametrize('name', ['input', 'result', 'reviewer'])
def test_independent_ai_prepare_checks_selected_schema_before_caches(tmp_path, name):
    import shutil
    from lib.stages import st08_prepare_ai
    from test_st08_prepare_ai import setup_source
    cfg, cache, out = setup_source(tmp_path, [])
    selected = tmp_path / 'selected-schemas'
    shutil.copytree(cfg['ai']['schemas_dir'], selected)
    cfg['ai']['schemas_dir'] = str(selected)
    (selected / (name + '.json')).write_text('{"type":"wrong"}', encoding='utf-8')
    with pytest.raises(ValueError, match='invalid JSON Schema') as error:
        st08_prepare_ai.run(cfg, str(tmp_path / 'missing-cache'), str(out))
    assert name + '.json' in str(error.value)
    assert not out.exists()


@pytest.mark.parametrize('data', [b'{', b'\xff', b'{"type":"string","type":"number"}',
                                b'{"const":NaN}'])
def test_decode_errors_preserve_legacy_prefix_and_details(tmp_path, data):
    from lib.content_checks import check_ai_result_schema
    path = tmp_path / 'broken.json'
    path.write_bytes(data)
    with pytest.raises(checks.SchemaDecodeError) as error:
        checks.load_schema(path)
    assert isinstance(error.value, ValueError)
    assert error.value.__cause__ is not None
    problem = check_ai_result_schema(path)
    assert problem.startswith('is not valid JSON')
    assert str(path) in problem
    assert str(error.value) in problem


@pytest.mark.parametrize('value', [{'type': 'wrong'}, {'$ref': '#/$defs/missing'},
                                 {'$ref': 'https://example.invalid/schema'}])
def test_schema_failures_are_not_misreported_as_decode_errors(tmp_path, value):
    import json
    from lib.content_checks import check_ai_result_schema
    path = tmp_path / 'invalid-schema.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError) as error:
        checks.load_schema(path)
    assert not isinstance(error.value, checks.SchemaDecodeError)
    assert check_ai_result_schema(path) == str(error.value)


def test_missing_schema_is_not_a_decode_error(tmp_path):
    from lib.content_checks import check_ai_result_schema
    path = tmp_path / 'missing.json'
    with pytest.raises(ValueError) as error:
        checks.load_schema(path)
    assert not isinstance(error.value, checks.SchemaDecodeError)
    problem = check_ai_result_schema(path)
    assert problem == str(error.value)
    assert 'cannot read schema' in problem
