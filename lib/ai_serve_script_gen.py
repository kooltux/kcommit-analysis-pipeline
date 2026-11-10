"""Read portable AI server source without inspecting or assembling helper code."""
import os

from lib.ai_code_assets import read_embedded_source

TOOL_MANIFEST_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'MANIFEST.json')


def build_main_source():
    """Read and syntax-check the base asset without executing runtime code."""
    return read_embedded_source('server').decode('utf-8')


_MAIN_SOURCE = build_main_source()
