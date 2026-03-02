#!/bin/bash
#
# session_always_apply.sh
#
# Claude Code hook that discovers .mdc context files with alwaysApply: true
# in .cursor/rules/ folder and returns their full content at session start.
#
# Triggered on: SessionStart
#
# This hook loads all alwaysApply context once at session start, avoiding
# repeated loading on every file read operation.
#

set -euo pipefail

# Read JSON input from stdin
json_input=$(cat)

# Extract cwd from input
cwd=$(echo "$json_input" | jq -r '.cwd // empty')

# Exit silently if no cwd
if [[ -z "$cwd" ]]; then
    exit 0
fi

# Find git repository root (exit silently if not in a git repo)
if ! repo_root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null); then
    exit 0
fi

# Resolve symlinks for consistent path comparison (macOS /var -> /private/var)
repo_root=$(cd "$repo_root" && pwd -P)

# Check for .cursor/rules/ folder (exit silently if not present)
cursor_rules_dir="$repo_root/.cursor/rules"
if [[ ! -d "$cursor_rules_dir" ]]; then
    exit 0
fi

# Function to parse frontmatter from an .mdc file
# Sets: fm_always_apply
parse_frontmatter() {
    local file="$1"
    fm_always_apply="false"

    # Check if file starts with ---
    if ! head -1 "$file" | grep -q '^---$'; then
        return 1
    fi

    # Extract frontmatter (between first and second ---)
    local frontmatter
    frontmatter=$(sed -n '2,/^---$/p' "$file" | sed '$d')

    # Parse YAML fields (simple line-by-line parsing)
    while IFS= read -r line; do
        # Skip empty lines
        [[ -z "$line" ]] && continue

        # Extract alwaysApply value
        if [[ "$line" =~ ^alwaysApply:[[:space:]]*(.*) ]]; then
            fm_always_apply="${BASH_REMATCH[1]}"
        fi
    done <<< "$frontmatter"

    return 0
}

# Function to extract content after frontmatter
extract_content() {
    local file="$1"

    # Find the line number of the second ---
    local end_line
    end_line=$(sed -n '2,${/^---$/=;q}' "$file" | head -1)

    if [[ -n "$end_line" ]]; then
        # Output everything after the frontmatter closing ---
        tail -n +"$((end_line + 1))" "$file"
    else
        # No frontmatter, return whole file
        cat "$file"
    fi
}

# Collect alwaysApply file contents
always_apply_content=""

# Scan all .mdc files in .cursor/rules/
for mdc_file in "$cursor_rules_dir"/*.mdc; do
    # Skip if no files found
    [[ -e "$mdc_file" ]] || continue

    # Parse frontmatter
    if ! parse_frontmatter "$mdc_file"; then
        continue
    fi

    # Only process alwaysApply files
    if [[ "$fm_always_apply" != "true" ]]; then
        continue
    fi

    # Get filename for header
    filename=$(basename "$mdc_file")

    # Extract content after frontmatter
    content=$(extract_content "$mdc_file")

    # Append to output with header
    if [[ -n "$always_apply_content" ]]; then
        always_apply_content+="\n\n"
    fi
    always_apply_content+="## $filename\n\n$content"
done

# Output JSON with additionalContext
if [[ -n "$always_apply_content" ]]; then
    # Add header and format as JSON
    full_content="# Cursor Context (Always Apply)\n\n$always_apply_content"

    json_output=$(jq -n \
        --arg ctx "$(echo -e "$full_content")" \
        '{
          hookSpecificOutput: {
            hookEventName: "SessionStart",
            additionalContext: $ctx
          }
        }')
    echo "$json_output"
fi

exit 0
