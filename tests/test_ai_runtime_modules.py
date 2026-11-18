"""Separate runtime modules retain shared validation and initialize before serving."""
import ast
import inspect
import subprocess
import sys
import zipfile

from lib import ai_workflow
from test_ai_package_server import app, package, snapshots


def test_packaged_workflow_functions_match_shared_source(app):
    with zipfile.ZipFile(app) as archive:
        tree = ast.parse(archive.read('kcap_ai_runtime/workflow.py'))
        base = ast.parse(archive.read('kcap_ai_runtime/server.py'))
    definitions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for function in (ai_workflow.assemble, ai_workflow.validate_role, ai_workflow.validate_workflow,
                     ai_workflow.validate_contribution_set):
        expected = ast.parse(inspect.getsource(function)).body[0]
        assert ast.dump(definitions[function.__name__]) == ast.dump(expected)
    roles = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'ROLES' for target in node.targets))
    assert ast.literal_eval(roles) == ai_workflow.ROLES
    names = {node.name for node in base.body if isinstance(node, ast.FunctionDef)}
    assert not names & {'assemble', 'validate_role', 'validate_workflow',
                        'source_context', 'contract_index', 'validate_contributions'}


def test_isolated_module_initialization_and_idempotent_install(app, tmp_path):
    program = """import sys
sys.path.insert(0, sys.argv[1])
sys.argv[0] = sys.argv[1]
from kcap_ai_runtime import server, versioned_routes
assert [(r['method'],r['path']) for r in server.ROUTES] == [('GET','/')]
versioned_routes.install()
keys=[(r['method'],r['path']) for r in server.ROUTES]
versioned_routes.install()
assert keys==[(r['method'],r['path']) for r in server.ROUTES]
assert len(keys)==len(set(keys))
assert all(path=='/' or path.startswith(('/v1/','/v2/')) for method,path in keys)
assert ('GET','/v1/api') in keys and ('GET','/v2/api') in keys
assert ('GET','/api') not in keys
server.ARCHIVE.close()
"""
    result = subprocess.run([sys.executable, '-I', '-S', '-c', program, str(app)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
