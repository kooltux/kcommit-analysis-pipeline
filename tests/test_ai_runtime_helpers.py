"""Portable helper definitions, prompt bytes and package identities stay shared."""
import ast
import inspect
import sys
import zipfile

from lib import ai_contract, ai_prompt_body
from ai_runtime_helpers import runtime_namespace
from test_ai_package_server import app, package, snapshots


def test_packaged_helper_definitions_match_shared_sources(app):
    groups = {
        'validation': (ai_contract.AssessmentValidationError,
                       ai_contract.result_properties, ai_contract.validate_result),
        'prompt_body': (ai_prompt_body.build_prompt_body,),
    }
    with zipfile.ZipFile(app) as archive:
        for name, functions in groups.items():
            tree = ast.parse(archive.read('kcap_ai_runtime/' + name + '.py'))
            definitions = {node.name: node for node in tree.body
                           if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
            for function in functions:
                expected = ast.parse(inspect.getsource(function)).body[0]
                assert ast.dump(definitions[function.__name__]) == ast.dump(expected)
        tree = ast.parse(archive.read('kcap_ai_runtime/prompt_body.py'))
    value = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'BODY_SCHEMAS'
                         for target in node.targets))
    assert ast.literal_eval(value) == ai_prompt_body.BODY_SCHEMAS


def test_packaged_helpers_preserve_identity_and_prompt_bytes(app, package):
    read = lambda path: package['files']['ai_contract/' + path]
    with runtime_namespace(app) as values:
        name = values['__package__']
        validation = sys.modules[name + '.validation']
        prompt_body = sys.modules[name + '.prompt_body']
        assert values['AssessmentValidationError'] is validation.AssessmentValidationError
        assert values['validate_result'] is validation.validate_result
        assert values['build_prompt_body'] is prompt_body.build_prompt_body
        for role in ai_prompt_body.BODY_SCHEMAS:
            assert values['build_prompt_body'](role, read) == ai_prompt_body.build_prompt_body(role, read)
    assert not any(key == name or key.startswith(name + '.') for key in sys.modules)
