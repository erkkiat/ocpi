#!/bin/bash

# Script to read all files in a logical flow group
# Usage: ./.claude/scripts/read_flow.sh authorization_flow

set -e

FLOW=$1
FILE_GROUPS=".claude/file_groups.json"

if [ -z "$FLOW" ]; then
    echo "Usage: ./scripts/read_flow.sh <flow_name>"
    echo ""
    echo "Available flows:"
    jq -r 'keys[]' "$FILE_GROUPS" 2>/dev/null || echo "Error: $FILE_GROUPS not found"
    exit 1
fi

if [ ! -f "$FILE_GROUPS" ]; then
    echo "Error: $FILE_GROUPS not found"
    exit 1
fi

# Check if flow exists
if ! jq -e ".$FLOW" "$FILE_GROUPS" > /dev/null 2>&1; then
    echo "Error: Flow '$FLOW' not found"
    echo ""
    echo "Available flows:"
    jq -r 'keys[]' "$FILE_GROUPS"
    exit 1
fi

# Get description
DESCRIPTION=$(jq -r ".$FLOW.description" "$FILE_GROUPS")
echo "=================================================="
echo "Flow: $FLOW"
echo "Description: $DESCRIPTION"
echo "=================================================="
echo ""

# Read and display each file
FILES=$(jq -r ".$FLOW.files[]" "$FILE_GROUPS")

for file in $FILES; do
    if [ -f "$file" ]; then
        echo "=========================================="
        echo "File: $file"
        echo "=========================================="
        cat "$file"
        echo ""
        echo ""
    else
        echo "⚠️  File not found: $file"
        echo ""
    fi
done

echo "=================================================="
echo "End of flow: $FLOW"
echo "=================================================="
