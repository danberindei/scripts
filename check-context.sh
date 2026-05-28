#!/usr/bin/env bash
input=$(cat)
transcript=$(echo "$input" | jq -r '.transcript_path // empty')
prompt=$(echo "$input" | jq -r '.prompt // empty')
session_id=$(echo "$input" | jq -r '.session_id // empty')

flag_file="/tmp/claude-session-summary-${session_id}"

# Allow session-summary invocations through regardless of context
if [[ -n "$prompt" ]] && echo "$prompt" | grep -qi 'session.summary\|/session-summary'; then
  [[ -n "$session_id" ]] && touch "$flag_file"
  exit 0
fi

# Allow tool calls that are part of an in-progress session-summary
if [[ -f "$flag_file" ]]; then
  exit 0
fi

if [[ -n "$transcript" && -f "$transcript" ]]; then
  input_tokens=$(tac "$transcript" | jq -Rn '
    first(inputs | fromjson? | select(.type=="assistant"))
    | .message.usage
    | (.input_tokens//0) + (.cache_creation_input_tokens//0) + (.cache_read_input_tokens//0)
  ' 2>/dev/null)
  limit=140000
  if [[ "$input_tokens" =~ ^[0-9]+$ ]] && ((input_tokens > limit)); then
    echo "Context at ${input_tokens} tokens (>${limit}) - write a summary of what you did and what's left, then stop." >&2
    exit 2
  fi
fi
exit 0
