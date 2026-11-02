"""Compose the complete static prompt served for each LLM role.

The body is the stored role prompt followed by the schemas that role reads, so it
is identical for every chunk and its size is known in advance. The orchestrator
appends only per-chunk data: trusted metadata, the source chunk and, for the
Reviewer, the validated specialist outputs. BODY_SCHEMAS and build_prompt_body
are embedded in the portable server: keep this module standard-library only and
free of imports.
"""

BODY_SCHEMAS = {
    'analyst': (('input', 'Input schema'), ('analyst', 'Output schema')),
    'cve': (('input', 'Input schema'), ('cve', 'Output schema')),
    'reviewer': (('input', 'Input schema'), ('analyst', 'Analyst schema'),
                 ('cve', 'CVE expert schema'), ('reviewer', 'Output schema')),
}


def build_prompt_body(name, read):
    """Return the role prompt plus its schemas; read(path) returns contract bytes."""
    parts = [read('prompts/' + name + '.md').decode('utf-8').rstrip('\n'), '', '## Artefacts']
    for schema, title in BODY_SCHEMAS[name]:
        text = read('schemas/' + schema + '.json').decode('utf-8').rstrip('\n')
        parts += ['', '### %s (%s.json)' % (title, schema), '```json', text, '```']
    return ('\n'.join(parts) + '\n').encode('utf-8')
