"""Snapshot the selected directory-only AI contract without writing outputs."""
from pathlib import Path

from lib.ai_contract import FIELDS, digest, result_properties
from lib.ai_prompts import ROLE, read_prompts
from lib.ai_schema_validation import parse_schema
from lib.resources import resource_path

PROMPT_ROLES = ('analyst', 'cve', 'reviewer', 'assembler')
SCHEMA_ROLES = ('input', 'analyst', 'cve', 'reviewer', 'result')
REVIEW_FIELDS = {'rv_agreement', 'rv_notes', 'rv_recommendation'}


def load_contract(cfg):
    ai = cfg.get('ai') or {}
    obsolete = {'prompt_path', 'result_schema_path'} & set(ai)
    if obsolete:
        raise ValueError('Removed AI settings: ' + ', '.join(sorted(obsolete)))
    prompts_dir = resource_path(cfg, ai.get('prompts_dir'), 'ai', 'prompts')
    schemas_dir = resource_path(cfg, ai.get('schemas_dir'), 'ai', 'schemas')
    prompts = read_prompts(prompts_dir)
    missing = {role + '.md' for role in PROMPT_ROLES} - set(prompts)
    if missing:
        raise ValueError('ai.prompts_dir: missing ' + ', '.join(sorted(missing)))
    try:
        root = Path(schemas_dir).resolve(strict=True)
        if not root.is_dir():
            raise ValueError('ai.schemas_dir: not a directory')
        entries = sorted(root.glob('*.json'), key=lambda item: item.name)
        snapshots = {}
        schemas = {}
        for entry in entries:
            if not ROLE.fullmatch(entry.stem):
                raise ValueError('Invalid schema filename: ' + entry.name)
            target = entry.resolve(strict=True)
            if not target.is_file():
                raise ValueError('Schema target is not a regular file: ' + entry.name)
            data = target.read_bytes()
            schemas[entry.stem] = parse_schema(data, str(entry))
            snapshots[entry.name] = data
    except (OSError, RuntimeError) as exc:
        raise ValueError('ai.schemas_dir: cannot snapshot ' + str(schemas_dir)) from exc
    missing = set(SCHEMA_ROLES) - set(schemas)
    if missing:
        raise ValueError('ai.schemas_dir: missing ' + ', '.join(sorted(missing)))
    try:
        input_fields = schemas['input']['properties']['commits']['items']['properties']
        if set(input_fields) != set(FIELDS):
            raise ValueError('AI input schema fields do not match the commit projection')
    except (KeyError, TypeError) as exc:
        raise ValueError('AI input schema must describe projected commits') from exc
    role_fields = {role: set(result_properties(schemas[role]))
                   for role in ('analyst', 'cve', 'reviewer')}
    if role_fields['reviewer'] != REVIEW_FIELDS:
        raise ValueError('Reviewer schema must define exactly the three review fields')
    if role_fields['cve'] != {'ai_cve_ids', 'ai_cve_probabilities'}:
        raise ValueError('CVE schema must define exactly the two CVE fields')
    seen = set()
    for role, fields in role_fields.items():
        if seen & fields:
            raise ValueError('Overlapping role assessment fields: ' + role)
        seen.update(fields)
        role_spec = schemas[role].get('properties', {}).get('role', {})
        if role_spec.get('const') != role or 'role' not in schemas[role].get('required', []):
            raise ValueError('Role schema must require its own identity: ' + role)
    if len(seen) != 18 or seen != set(result_properties(schemas['result'])):
        raise ValueError('Final schema must define the exact 18-field role union')
    if 'role' in schemas['result'].get('properties', {}):
        raise ValueError('Final schema must not define a role field')
    files = {'prompts/' + name: data for name, data in prompts.items()}
    files.update({'schemas/' + name: data for name, data in snapshots.items()})
    files = dict(sorted(files.items()))
    return {'files': files, 'schemas': schemas,
            'checksums': {name: digest(data) for name, data in files.items()}}
