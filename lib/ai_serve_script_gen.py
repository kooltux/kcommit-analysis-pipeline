"""Assemble portable AI server source from trusted static Python assets."""
import inspect
import os

from lib.ai_code_assets import read_embedded_source
from lib.ai_contract import AssessmentValidationError, result_properties, validate_result
from lib.ai_prompt_body import BODY_SCHEMAS, build_prompt_body

_RESULT_VALIDATION_SOURCE = '\n\n'.join(inspect.getsource(fn) for fn in (AssessmentValidationError, result_properties, validate_result))
_BODY_SOURCE = 'BODY_SCHEMAS = ' + repr(BODY_SCHEMAS) + '\n\n\n' + inspect.getsource(build_prompt_body)

TOOL_MANIFEST_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'MANIFEST.json')


def build_main_source():
    """Read and syntax-check the base asset without executing runtime code."""
    source = read_embedded_source('server').decode('utf-8')
    return _RESULT_VALIDATION_SOURCE + '\n' + _BODY_SOURCE + '\n' + source


_MAIN_SOURCE = build_main_source()
