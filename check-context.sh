#!/usr/bin/env bash
transcript=$(cat | jq -r '.transcript_path // empty')
if [[ -n "$transcript" && -f "$transcript" ]]; then
  input_tokens=$(tac "$transcript" | jq -Rn '
    first(inputs | fromjson? | select(.type=="assistant"))
    | .message.usage
    | (.input_tokens//0) + (.cache_creation_input_tokens//0) + (.cache_read_input_tokens//0)
  ' 2>/dev/null)
  limit=140000
  if [[ "$input_tokens" =~ ^[0-9]+$ ]] && ((input_tokens > limit)); then
    echo "Context at ${input_tokens} tokens (>${limit}) - run /compact or start a new session." >&2
    exit 2
  fi
fi
exit 0
