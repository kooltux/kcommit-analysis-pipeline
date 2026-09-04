#!/bin/bash
# archive_output.sh - Create timestamped archive of pipeline output
#
# This script is self-contained and portable. It determines its own location
# and can be copied to the output/ directory. When run, it archives the
# output/ folder where it resides.
#
# Usage:
#   archive_output.sh [config_file]
#
# Arguments:
#   config_file - Optional. Path to pipeline config JSON. If not provided,
#                 looks for pipeline_config.json in the same directory.
#
# Creates:
#   kernel_commit_analysis_<rev_old>_<rev_new>_<YYYYMMDD>.tar.gz
#
# Requirements:
#   - Must be run from or have access to the output/ directory
#   - Config file must contain kernel.rev_old and kernel.rev_new

set -e

# Get the directory where this script resides
# This is typically the output/ directory after pipeline run
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Find json_query.sh in the same directory
JSON_QUERY="$SCRIPT_DIR/json_query.sh"

if [ ! -x "$JSON_QUERY" ]; then
    echo "Error: json_query.sh not found or not executable in $SCRIPT_DIR" >&2
    exit 1
fi

# Determine config file
if [ $# -eq 0 ]; then
    CONFIG_FILE="$SCRIPT_DIR/pipeline_config.json"
else
    CONFIG_FILE="$1"
    # If relative path, resolve it
    if [[ "$CONFIG_FILE" != /* ]]; then
        CONFIG_FILE="$(pwd)/$CONFIG_FILE"
    fi
fi

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Config file '$CONFIG_FILE' not found" >&2
    exit 1
fi

# Extract kernel version range from config
REV_OLD=$("$JSON_QUERY" "$CONFIG_FILE" kernel.rev_old)
REV_NEW=$("$JSON_QUERY" "$CONFIG_FILE" kernel.rev_new)

if [ -z "$REV_OLD" ] || [ -z "$REV_NEW" ]; then
    echo "Error: Could not extract kernel.rev_old or kernel.rev_new from config" >&2
    echo "Config file: $CONFIG_FILE" >&2
    exit 1
fi

# Generate timestamp
TIMESTAMP=$(date +%Y%m%d)

# Sanitize version strings (remove problematic chars for filenames)
REV_OLD_SAFE=$(echo "$REV_OLD" | tr -cd '[:alnum:]._-')
REV_NEW_SAFE=$(echo "$REV_NEW" | tr -cd '[:alnum:]._-')

# Build archive name
ARCHIVE_NAME="kernel_commit_analysis_${REV_OLD_SAFE}_${REV_NEW_SAFE}_${TIMESTAMP}.tar.gz"

# Determine where to place the archive
# If WORKSPACE is set, use it; otherwise, use the script's directory
if [ -n "$WORKSPACE" ]; then
    ARCHIVE_PATH="$WORKSPACE/$ARCHIVE_NAME"
    OUTPUT_DIR="$WORKSPACE/output"
else
    ARCHIVE_PATH="$SCRIPT_DIR/$ARCHIVE_NAME"
    OUTPUT_DIR="$SCRIPT_DIR"
fi

# Check if output directory exists
if [ ! -d "$OUTPUT_DIR" ]; then
    echo "Error: Output directory '$OUTPUT_DIR' not found" >&2
    exit 1
fi

echo "Creating archive: $ARCHIVE_PATH"
echo "  From: $REV_OLD"
echo "  To:   $REV_NEW"
echo "  Date: $TIMESTAMP"

# Create the archive
tar zcf "$ARCHIVE_PATH" -C "$(dirname "$OUTPUT_DIR")" "$(basename "$OUTPUT_DIR")"

echo "Archive created successfully: $ARCHIVE_PATH"
echo "Size: $(du -h "$ARCHIVE_PATH" | cut -f1)"
