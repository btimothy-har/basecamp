#!/bin/bash
#
# cursor_discovery.sh
#
# Claude Code hook that discovers .mdc context files in .cursor/rules/ folder
# and returns appropriate context based on frontmatter rules.
#
# Triggered on: PreToolUse (Read)
#
# Rules:
#   - alwaysApply: true → Skip (loaded at SessionStart by session_always_apply.sh)
#   - globs match file being read → MANDATORY context (instruct Claude to READ)
#   - globs don't match → Skip
#   - no globs (and alwaysApply: false) → OPTIONAL misc context with description
#

set -euo pipefail

# Read JSON input from stdin
json_input=$(cat)

# Extract file_path from tool_input
file_path=$(echo "$json_input" | jq -r '.tool_input.file_path // empty')

# Exit silently if no file path
if [[ -z "$file_path" ]]; then
    exit 0
fi

# Resolve to absolute path if relative
if [[ ! "$file_path" = /* ]]; then
    cwd=$(echo "$json_input" | jq -r '.cwd // empty')
    if [[ -n "$cwd" ]]; then
        file_path="$cwd/$file_path"
    fi
fi

# Get directory of the file being read
file_dir=$(dirname "$file_path")

# Find git repository root (exit silently if not in a git repo)
if ! repo_root=$(git -C "$file_dir" rev-parse --show-toplevel 2>/dev/null); then
    exit 0
fi

# Resolve symlinks for consistent path comparison (macOS /var -> /private/var)
# Use repo_root as base if file directory doesn't exist yet
if [[ -d "$(dirname "$file_path")" ]]; then
    file_path=$(cd "$(dirname "$file_path")" && pwd -P)/$(basename "$file_path")
fi
repo_root=$(cd "$repo_root" && pwd -P)

# Check for .cursor/rules/ folder (exit silently if not present)
cursor_rules_dir="$repo_root/.cursor/rules"
if [[ ! -d "$cursor_rules_dir" ]]; then
    exit 0
fi

# Get relative path of file from repo root (for glob matching)
rel_file_path="${file_path#$repo_root/}"

# Arrays to collect context files
mandatory_files=()
optional_files=()

# Function to check if a path matches a glob pattern
# Supports patterns like: dbt/**, *.py, src/**/*.ts
matches_glob() {
    local path="$1"
    local pattern="$2"

    # Empty pattern means no match
    [[ -z "$pattern" ]] && return 1

    # Handle ** patterns (recursive directory matching)
    if [[ "$pattern" == *"/**" ]]; then
        # Pattern like "src/**" - matches anything under src/
        local prefix="${pattern%/**}"
        # Check if path starts with prefix/ (unquoted for glob expansion)
        # shellcheck disable=SC2254
        case "$path" in
            $prefix/*) return 0 ;;
            $prefix) return 0 ;;
        esac
        return 1
    elif [[ "$pattern" == *"/**/"* ]]; then
        # Pattern like "src/**/test.py" - recursive with suffix
        local before="${pattern%%/**/*}"
        local after="${pattern#*/**/}"
        # Path must start with before/ and end with after
        # shellcheck disable=SC2254
        case "$path" in
            $before/*$after) return 0 ;;
        esac
        return 1
    else
        # Simple glob pattern - use case for pattern matching
        # shellcheck disable=SC2254
        case "$path" in
            $pattern) return 0 ;;
        esac
        return 1
    fi
}

# Function to parse frontmatter from an .mdc file
# Sets: fm_description, fm_globs, fm_always_apply
parse_frontmatter() {
    local file="$1"
    fm_description=""
    fm_globs=""
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

        # Extract key-value pairs
        if [[ "$line" =~ ^description:[[:space:]]*(.*) ]]; then
            fm_description="${BASH_REMATCH[1]}"
        elif [[ "$line" =~ ^globs:[[:space:]]*(.*) ]]; then
            fm_globs="${BASH_REMATCH[1]}"
        elif [[ "$line" =~ ^alwaysApply:[[:space:]]*(.*) ]]; then
            fm_always_apply="${BASH_REMATCH[1]}"
        fi
    done <<< "$frontmatter"

    return 0
}

# Scan all .mdc files in .cursor/rules/
for mdc_file in "$cursor_rules_dir"/*.mdc; do
    # Skip if no files found (nullglob handles this, but be safe)
    [[ -e "$mdc_file" ]] || continue

    # Parse frontmatter
    if ! parse_frontmatter "$mdc_file"; then
        continue
    fi

    # Get relative path from repo root for display
    rel_mdc_path="${mdc_file#$repo_root/}"

    # Apply rules
    if [[ "$fm_always_apply" == "true" ]]; then
        # Skip - loaded at session start by session_always_apply.sh
        continue
    elif [[ -n "$fm_globs" ]]; then
        # Has globs - check if they match
        if matches_glob "$rel_file_path" "$fm_globs"; then
            # Rule 2: globs match → MANDATORY
            mandatory_files+=("$rel_mdc_path|matches glob: $fm_globs")
        fi
        # Rule 3: globs don't match → Skip (do nothing)
    else
        # Rule 4: no globs (and not alwaysApply) → OPTIONAL with description
        if [[ -n "$fm_description" ]]; then
            optional_files+=("$rel_mdc_path|$fm_description")
        else
            optional_files+=("$rel_mdc_path|No description")
        fi
    fi
done

# Build output message
output_msg=""

if [[ ${#mandatory_files[@]} -gt 0 ]]; then
    output_msg+="RELEVANT CONTEXT FILES FOUND - these files MUST be read:\n"
    for item in "${mandatory_files[@]}"; do
        path="${item%%|*}"
        reason="${item#*|}"
        output_msg+="  - $path ($reason)\n"
    done
fi

if [[ ${#optional_files[@]} -gt 0 ]]; then
    if [[ -n "$output_msg" ]]; then
        output_msg+="\n"
    fi
    output_msg+="These additional context files may be helpful for review:\n"
    for item in "${optional_files[@]}"; do
        path="${item%%|*}"
        desc="${item#*|}"
        output_msg+="  - $path: $desc\n"
    done
fi

# Always output valid JSON for Claude Code to parse
# Format as JSON output with permissionDecision: "allow" to auto-approve
# Include additionalContext only if we have context files to report
if [[ -n "$output_msg" ]]; then
    json_output=$(jq -n \
        --arg ctx "$(echo -e "$output_msg")" \
        '{
          hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "allow",
            additionalContext: $ctx
          }
        }')
else
    json_output=$(jq -n \
        '{
          hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "allow"
          }
        }')
fi
echo "$json_output"

exit 0
