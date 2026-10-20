#!/usr/bin/env python3
"""Convert manual CSV assessments to the original server-compatible chunk JSONs."""
import argparse
import csv
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.ai_exchange import Assessments, Progress, WorkPackage, discover
from lib.ai_contract import encode, validate_result
from lib.config import load_config


def cell_value(raw, spec):
    raw = raw.strip()
    if spec['type'] == 'boolean':
        if raw.lower() not in ('true', 'false'):
            raise ValueError('Expected TRUE or FALSE')
        return raw.lower() == 'true'
    if spec['type'] == 'array':
        if raw in ('', 'EMPTY'):
            return []
        value = json.loads(raw) if raw.startswith('[') else [raw]
        if not isinstance(value, list):
            raise ValueError('Expected an array')
        if spec['items']['type'] == 'integer':
            if any(type(v) is not int and (not isinstance(v, str) or
                   not re.fullmatch(r'[+-]?[0-9]+', v)) for v in value):
                raise ValueError('Expected integer probabilities')
            value = [int(v) for v in value]
        return value
    return '' if raw == 'EMPTY' else raw


def convert(cfg, inputs, output_dir, rationale_from_summary=False):
    progress = Progress('ai-csv')
    package = WorkPackage(cfg, progress)
    files = discover(inputs, '.csv', progress)
    props = package.schema['properties']['results']['additionalProperties']['properties']
    accepted = Assessments(progress)
    rows = 0
    ignored = set()
    if rationale_from_summary:
        progress.say('Compatibility option enabled: missing categorisation rationale copied from ai_summary')
    for index, filename in enumerate(files, 1):
        with filename.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream, strict=True)
            fields = reader.fieldnames or []
            if len(fields) != len(set(fields)) or 'commit_hash' not in fields:
                raise ValueError(f'{filename}: duplicate headers or missing commit_hash')
            extra = set(fields) - set(props) - {'commit_hash'}
            unknown = {key for key in extra if key not in ('extracted_Filename', 'ai_cve_id_pattern')
                       and not key.startswith('rv_')}
            if unknown:
                raise ValueError(f'{filename}: unknown columns {sorted(unknown)}')
            if extra - ignored:
                progress.say(f'{filename}: ignoring non-contract columns {sorted(extra - ignored)}')
                ignored.update(extra)
            for row in reader:
                origin = f'{filename}:line {reader.line_num}'
                try:
                    if None in row or any(v is None for v in row.values()):
                        raise ValueError('Row does not match header width')
                    sha = row['commit_hash'].strip()
                    item = {}
                    for key, spec in props.items():
                        raw = row.get(key)
                        if key == 'ai_categorisation_rationale' and raw in (None, '', 'EMPTY') and rationale_from_summary:
                            raw = row.get('ai_summary')
                        if key == 'ai_cve_probabilities' and raw is None:
                            raw = ''
                        if raw is None:
                            raise ValueError('Missing required column: ' + key)
                        item[key] = cell_value(raw, spec)
                    package.validate_item(sha, item)
                    accepted.add(sha, item, origin)
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError(f'{origin}: {exc}') from exc
                rows += 1
                progress.say(f'File {index}/{len(files)} {filename}: {rows} rows; '
                             f'{len(accepted.results)} unique commits', False)
        progress.say(f'Read CSV {index}/{len(files)}: {filename}; {rows} rows', index in (1, len(files)))
    grouped = {}
    for sha, item in accepted.results.items():
        grouped.setdefault(package.by_sha[sha], {})[sha] = item
    if not grouped:
        raise ValueError('No assessments found; no output written')
    documents = {name: package.envelope(name, values) for name, values in sorted(grouped.items())}
    progress.say(f'Validating {len(documents)} output chunks before writing')
    for name, value in documents.items():
        validate_result(value, package.chunks[name], package.schema, value['input_checksum'])
    root = Path(output_dir)
    if root.exists() or root.is_symlink():
        raise ValueError(f'Output directory already exists; refusing overwrite: {root}')
    root.mkdir(parents=True)
    for index, (name, value) in enumerate(documents.items(), 1):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(encode(value))
        progress.say(f'Wrote chunk {index}/{len(documents)}: {target}', index in (1, len(documents)))
    complete = sum(v['analysis_status'] == 'complete' for v in documents.values())
    progress.say(f'Done: {len(files)} files read; {len(documents)} written '
                 f'({complete} complete, {len(documents) - complete} partial); {accepted.summary()}')
    return {'files_written': len(documents), 'analyzed_commits': len(accepted.results)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, help='Original or generated pipeline_config.json')
    parser.add_argument('--output-dir', required=True, help='New directory for server-compatible result JSONs')
    parser.add_argument('--rationale-from-summary', action='store_true')
    parser.add_argument('inputs', nargs='+', help='CSV files or recursively scanned directories')
    args = parser.parse_args(argv)
    try:
        print(f'[ai-csv] Configuration: {Path(args.config).absolute()}', file=sys.stderr, flush=True)
        result = convert(load_config(args.config), args.inputs, args.output_dir, args.rationale_from_summary)
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(1, f'ERROR: {exc}\n')
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
