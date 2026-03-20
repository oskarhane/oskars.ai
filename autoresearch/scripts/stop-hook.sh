#!/bin/bash
# Stop hook for autoresearch plugin.
# Blocks stop when an autoresearch session is active (autoresearch.jsonl exists).
# Reads JSON from stdin with { cwd, stop_hook_active } fields.

input=$(cat)
cwd=$(echo "$input" | jq -r '.cwd // empty')
stop_hook_active=$(echo "$input" | jq -r '.stop_hook_active // false')

# Prevent infinite resume loops
if [ "$stop_hook_active" = "true" ]; then
  exit 0
fi

# Check for active autoresearch session
if [ -n "$cwd" ] && [ -f "$cwd/autoresearch.jsonl" ]; then
  echo '{"decision":"block","reason":"Autoresearch session active. Resume: read autoresearch.md and git log, then continue the loop."}'
  exit 0
fi

exit 0
