#!/usr/bin/env bash
# Shared template rendering for Claude Code skills.
# Usage: render_template <file> VAR1=value1 VAR2=value2 ...
# Replaces {VAR} placeholders. Fails if any {ALLCAPS} placeholders remain unfilled.

render_template() {
    local file="$1"; shift
    if [[ ! -f "$file" ]]; then
        echo "render_template: file not found: $file" >&2
        return 1
    fi
    local result
    result=$(<"$file")
    while [[ $# -gt 0 ]]; do
        local key="${1%%=*}"
        local val="${1#*=}"
        result="${result//\{$key\}/$val}"
        shift
    done
    # Check for unfilled placeholders (only ALLCAPS_UNDERSCORES patterns)
    local unfilled
    unfilled=$(echo "$result" | grep -oE '\{[A-Z][A-Z_]+\}' | sort -u)
    if [[ -n "$unfilled" ]]; then
        echo "render_template: unfilled placeholders in $file:" >&2
        echo "$unfilled" >&2
        return 1
    fi
    printf '%s' "$result"
}
