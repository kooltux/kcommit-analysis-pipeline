"""Static server assembly retains shared prefixes without executing runtime code."""
import ast
import inspect
from pathlib import Path

import lib.ai_code_assets as assets
from lib import ai_contract, ai_prompt_body
from lib import ai_serve_script_gen as server


def test_base_server_source_preserves_shared_prefixes_and_static_bytes():
    validation = '\n\n'.join(inspect.getsource(fn) for fn in
        (ai_contract.AssessmentValidationError, ai_contract.result_properties, ai_contract.validate_result))
    body = ('BODY_SCHEMAS = ' + repr(ai_prompt_body.BODY_SCHEMAS) + '\n\n\n'
            + inspect.getsource(ai_prompt_body.build_prompt_body))
    data = assets.read_embedded_source('server')
    expected = validation + '\n' + body + '\n' + data.decode('utf-8')
    assert server.build_main_source() == expected
    assert server._MAIN_SOURCE == expected
    compile(expected, 'kcap_ai_runtime/server.py', 'exec')


def test_host_no_longer_contains_a_main_source_literal():
    tree = ast.parse(Path(server.__file__).read_text(encoding='utf-8'))
    constants = [node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == '_MAIN_SOURCE'
                         for target in node.targets)
                 and isinstance(node.value, ast.Constant)]
    assert not constants


def test_base_server_builder_reads_fresh_without_executing(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, 'ASSET_DIR', str(tmp_path))
    path = tmp_path / assets.ASSET_FILES['server']
    first = b'raise RuntimeError("must not execute during generation")\n'
    path.write_bytes(first)
    assert server.build_main_source().encode('utf-8').endswith(first)
    second = first + b'# Fresh base source.\n'
    path.write_bytes(second)
    assert server.build_main_source().encode('utf-8').endswith(second)
