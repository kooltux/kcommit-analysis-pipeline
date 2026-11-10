"""Import a zipapp runtime in a unique package namespace and clean it up."""
from contextlib import contextmanager
import importlib
from pathlib import Path
import sys
from types import ModuleType
import uuid


@contextmanager
def runtime_namespace(app):
    name = '_kcap_test_' + uuid.uuid4().hex
    package = ModuleType(name)
    package.__path__ = [str(Path(app).resolve()) + '/kcap_ai_runtime']
    previous_argv = sys.argv
    sys.argv = [str(app)]
    sys.modules[name] = package
    module = None
    try:
        module = importlib.import_module(name + '.server')
        yield vars(module)
    finally:
        if module is not None:
            module.ARCHIVE.close()
        for key in list(sys.modules):
            if key == name or key.startswith(name + '.'):
                sys.modules.pop(key, None)
        sys.argv = previous_argv
