#!/bin/bash
# Stop hook for autoresearch plugin.
# Blocks stop when an autoresearch session is active (.research/*/autoresearch.jsonl exists).
# Allows exit when maxIterations is set and reached.
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
  jsonl_path=$(find "$cwd/.research" -maxdepth 2 -name "autoresearch.jsonl" -print -quit 2>/dev/null)
  if [ -n "$jsonl_path" ]; then
    research_dir=$(dirname "$jsonl_path")

    # Find last config header and extract maxIterations and segment
    last_config=$(grep '"type"' "$jsonl_path" | grep '"config"' | tail -1)
    if [ -n "$last_config" ]; then
      max_iterations=$(echo "$last_config" | jq -r '.maxIterations // empty')
      segment=$(echo "$last_config" | jq -r '.segment // 0')

      # If maxIterations is set (non-null, non-empty, numeric), check if limit reached
      if [ -n "$max_iterations" ] && [ "$max_iterations" != "null" ]; then
        # Count result lines in current segment
        result_count=$(grep '"type"' "$jsonl_path" | grep '"result"' | jq -c "select(.segment == $segment)" | wc -l | tr -d ' ')

        if [ "$result_count" -ge "$max_iterations" ] 2>/dev/null; then
          # Max iterations reached — allow exit
          exit 0
        fi
      fi
    fi

    echo "{\"decision\":\"block\",\"reason\":\"Autoresearch session active in $research_dir. Resume: read $research_dir/autoresearch.md and git log, then continue the loop.\"}"
    exit 0
  fi
fi

exit 0
