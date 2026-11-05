"""Explicitly build role submissions from final assessment fixtures."""
import json
import zipfile

from lib.ai_contract import encode, result_properties


def role_body(app, value):
    final = json.loads(value) if isinstance(value, (bytes, str)) else value
    documents = {}
    with zipfile.ZipFile(app) as archive:
        for role in ('analyst', 'cve', 'reviewer'):
            schema = json.loads(archive.read('ai_contract/schemas/' + role + '.json'))
            fields = result_properties(schema)
            documents[role] = dict(run_id=final['run_id'], source_chunk=final['source_chunk'],
                role=role, results={sha: {key: record[key] for key in fields if key in record}
                                   for sha, record in final['results'].items()})
    return encode(documents)
