"""Resolve product resources without implicit access to the tool's sample tree."""
import os


def resource_path(cfg, path=None, *default_parts):
    """Resolve resources against the initial anchor; hand-built configs may supply it."""
    cfg = cfg or {}
    meta = cfg.get('_meta') or {}
    anchor = (meta.get('initial_config_dir') or meta.get('config_dir') or
              cfg.get('config_dir') or os.getcwd())
    value = os.fspath(path) if path else os.path.join(*default_parts)
    return os.path.abspath(os.path.join(anchor, value))
