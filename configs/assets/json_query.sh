#!/bin/bash
# json_query.sh - Query JSON files using dotted notation
#
# This script is self-contained and portable. It determines its own location
# and can be copied to any directory (e.g., output/) and run from anywhere.
#
# Usage:
#   json_query.sh <file> <key.path>
#
# Examples:
#   json_query.sh pipeline_config.json kernel.rev_old
#   json_query.sh pipeline_config.json paths.work_dir
#   result=$(json_query.sh pipeline_config.json reports.outputs)
#
# Exit codes:
#   0 - Success
#   1 - Error (file not found, invalid JSON, key not found, wrong args)

set -e

# Get the directory where this script resides
# This works even when the script is invoked from a different directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    echo "Usage: $(basename "$0") <file> <key.path>" >&2
    echo "Example: $(basename "$0") pipeline_config.json kernel.rev_old" >&2
    echo "" >&2
    echo "Query a JSON file using dotted notation (e.g., 'a.b.c' for {a:{b:{c:value}}})" >&2
    echo "Returns scalars as plain text, objects/arrays as compact JSON." >&2
}

if [ $# -ne 2 ]; then
    usage
    exit 1
fi

FILE="$1"
KEY_PATH="$2"

# Resolve file path relative to current directory if not absolute
if [[ "$FILE" != /* ]]; then
    FILE="$(pwd)/$FILE"
fi

if [ ! -f "$FILE" ]; then
    echo "Error: File '$FILE' not found" >&2
    exit 1
fi

# Use Python to parse and query JSON
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
        print("Usage: json_query.sh <file> <key.path>", file=sys.stderr)
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
