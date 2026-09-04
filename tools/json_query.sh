#!/bin/bash
# json_query.sh - Query JSON files using dotted notation
#
# Usage:
#   json_query <file> <key.path>
#
# Examples:
#   json_query config.json kernel.rev_old
#   json_query config.json paths.work_dir
#   result=$(json_query config.json reports.outputs)

set -e

if [ $# -ne 2 ]; then
    echo "Usage: json_query <file> <key.path>" >&2
    echo "Example: json_query config.json kernel.rev_old" >&2
    return 1
fi

FILE="$1"
KEY_PATH="$2"

if [ ! -f "$FILE" ]; then
    echo "Error: File '$FILE' not found" >&2
    return 1
fi

python3 - "$FILE" "$KEY_PATH" <<'PYTHON'
import sys
import json

def get_nested(data, keys):
    """Navigate nested dict using list of keys."""
    for key in keys:
        if isinstance(data, dict) and key in data:
            data = data[key]
        else:
            raise KeyError(f"Key '{key}' not found")
    return data

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: json_query <file> <key.path>", file=sys.stderr)
        sys.exit(1)
    
    file_path = sys.argv[1]
    key_path = sys.argv[2]
    
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        keys = key_path.split('.')
        result = get_nested(data, keys)
        
        # If scalar (str, int, float, bool, None), print as-is
        if isinstance(result, (str, int, float, bool)) or result is None:
            print(result)
        else:
            # For objects/arrays, print as compact JSON
            print(json.dumps(result, separators=(',', ':')))
    
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in '{file_path}': {e}", file=sys.stderr)
        sys.exit(1)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
PYTHON
