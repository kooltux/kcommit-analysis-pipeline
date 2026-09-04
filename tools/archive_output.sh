#!/bin/bash
# archive_output.sh - Create timestamped archive of pipeline output
#
# Usage:
#   archive_output.sh <config_file>
#
# Creates: kernel_commit_analysis_<rev_old>_<rev_new>_<YYYYMMDD>.tar.gz
#
# Requirements:
#   - WORKSPACE environment variable must be set
#   - config_file must be a valid pipeline config JSON

set -e

if [ $# -ne 1 ]; then
    echo "Usage: archive_output.sh <config_file>" >&2
    echo "Example: archive_output.sh configs/my_config.json" >&2
    exit 1
fi

CONFIG_FILE="$1"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Config file '$CONFIG_FILE' not found" >&2
    exit 1
fi

if [ -z "$WORKSPACE" ]; then
    echo "Error: WORKSPACE environment variable is not set" >&2
    exit 1
fi

# Source the json_query function
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/json_query.sh"

# Extract kernel version range from config
REV_OLD=$(json_query "$CONFIG_FILE" kernel.rev_old)
REV_NEW=$(json_query "$CONFIG_FILE" kernel.rev_new)

if [ -z "$REV_OLD" ] || [ -z "$REV_NEW" ]; then
    echo "Error: Could not extract kernel.rev_old or kernel.rev_new from config" >&2
    exit 1
fi

# Generate timestamp
TIMESTAMP=$(date +%Y%m%d)

# Sanitize version strings (replace problematic chars)
REV_OLD_SAFE=$(echo "$REV_OLD" | tr -cd '[:alnum:]._-')
REV_NEW_SAFE=$(echo "$REV_NEW" | tr -cd '[:alnum:]._-')

# Build archive name
ARCHIVE_NAME="kernel_commit_analysis_${REV_OLD_SAFE}_${REV_NEW_SAFE}_${TIMESTAMP}.tar.gz"
ARCHIVE_PATH="$WORKSPACE/$ARCHIVE_NAME"

# Check if output directory exists
if [ ! -d "$WORKSPACE/output" ]; then
    echo "Error: Output directory '$WORKSPACE/output' not found" >&2
    exit 1
fi

echo "Creating archive: $ARCHIVE_PATH"
echo "  From: $REV_OLD"
echo "  To:   $REV_NEW"
echo "  Date: $TIMESTAMP"

# Create the archive
tar zcf "$ARCHIVE_PATH" -C "$WORKSPACE" output

echo "Archive created successfully: $ARCHIVE_PATH"
echo "Size: $(du -h "$ARCHIVE_PATH" | cut -f1)"
