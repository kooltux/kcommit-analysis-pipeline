#!/bin/bash
# archive_output.sh - Create timestamped archive of pipeline output
#
# This script is self-contained and portable. It is copied into
# output/scripts/ by the pipeline (stage 07). It determines its own
# location and archives the output/ directory it lives under (its
# parent directory), regardless of where it is invoked from.
#
# Usage:
#   archive_output.sh [config_file]
#
# Arguments:
#   config_file - Optional. Path to pipeline config JSON. If not provided,
#                 looks for pipeline_config.json in the parent directory
#                 (the output/ directory).
#
# Creates:
#   kernel_commit_analysis_<rev_old>_<rev_new>_<YYYYMMDD>.tar.gz
#
# Requirements:
#   - Must be in output/scripts/ (or a directory laid out the same way)
#   - json_query.sh must be in the same directory as this script
#   - Config file must contain kernel.rev_old and kernel.rev_new

set -e

# Get the directory where this script resides (e.g., output/scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parent directory is the output directory (e.g., output/)
OUTPUT_DIR="$(dirname "$SCRIPT_DIR")"

# Find json_query.sh in the same directory as this script
JSON_QUERY="$SCRIPT_DIR/json_query.sh"

if [ ! -x "$JSON_QUERY" ]; then
    echo "Error: json_query.sh not found or not executable in $SCRIPT_DIR" >&2
    exit 1
fi

# Determine config file
if [ $# -eq 0 ]; then
    CONFIG_FILE="$OUTPUT_DIR/pipeline_config.json"
else
    CONFIG_FILE="$1"
    # If relative path, resolve it against the caller's cwd
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

# Determine where to place the archive.
# If WORKSPACE is set, drop the archive there; otherwise, drop it next to
# the output/ directory (i.e., in OUTPUT_DIR's parent).
if [ -n "$WORKSPACE" ]; then
    ARCHIVE_PATH="$WORKSPACE/$ARCHIVE_NAME"
else
    ARCHIVE_PATH="$(dirname "$OUTPUT_DIR")/$ARCHIVE_NAME"
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

# Create the archive from the output directory (tar -C into its parent so
# the archive contains a single top-level folder named after OUTPUT_DIR).
tar zcf "$ARCHIVE_PATH" -C "$(dirname "$OUTPUT_DIR")" "$(basename "$OUTPUT_DIR")"

echo "Archive created successfully: $ARCHIVE_PATH"
echo "Size: $(du -h "$ARCHIVE_PATH" | cut -f1)"
