#!/bin/bash
set -euo pipefail

# Read the tool input from stdin
input=$(cat)

# Extract the command from the Bash tool input
command=$(echo "$input" | jq -r '.tool_input.command // empty')

# Only intercept git commit commands
if ! echo "$command" | grep -qE 'git\s+commit'; then
  exit 0
fi

# Run make check from the project root
cd "$CLAUDE_PROJECT_DIR"
if output=$(make check 2>&1); then
  exit 0
else
  echo "make check failed. Fix the issues before committing:" >&2
  echo "$output" >&2
  exit 2
fi
