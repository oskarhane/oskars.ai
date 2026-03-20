#!/bin/bash
# Stop hook for autoresearch plugin.
# Blocks stop when an autoresearch session is active (.research/*/autoresearch.jsonl exists).
# Reads JSON from stdin with { cwd, stop_hook_active } fields.

input=$(cat)
cwd=$(echo "$input" | jq -r '.cwd // empty')
stop_hook_active=$(echo "$input" | jq -r '.stop_hook_active // false')

# Prevent infinite resume loops
if [ "$stop_hook_active" = "true" ]; then
  exit 0
fi

# Check for active autoresearch session
if [ -n "$cwd" ]; then
  session_dir=$(find "$cwd/.research" -maxdepth 2 -name "autoresearch.jsonl" -print -quit 2>/dev/null)
  if [ -n "$session_dir" ]; then
    research_dir=$(dirname "$session_dir")
    echo "{\"decision\":\"block\",\"reason\":\"Autoresearch session active in $research_dir. Resume: read $research_dir/autoresearch.md and git log, then continue the loop.\"}"
    exit 0
  fi
fi

exit 0
