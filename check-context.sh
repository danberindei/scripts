#!/usr/bin/env bash
# Claude Code UserPromptSubmit + PreToolUse hook (~/.claude/settings.json).
# Blocks when context exceeds the token limit and directs the agent to run /session-handoff.
limit=150000

input=$(cat)
transcript=$(echo "$input" | jq -r '.transcript_path // empty')
prompt=$(echo "$input" | jq -r '.prompt // empty')
session_id=$(echo "$input" | jq -r '.session_id // empty')

if [[ -n "$session_id" ]]; then
  flag_file="/tmp/claude-session-handoff-${session_id}"

  # Allow session-handoff invocations through regardless of context
  if [[ -n "$prompt" ]] && echo "$prompt" | grep -qi 'session.handoff\|/session-handoff'; then
    touch "$flag_file"
    exit 0
  fi

  # Allow tool calls that are part of an in-progress session-handoff
  if [[ -f "$flag_file" ]]; then
    exit 0
  fi
fi

if [[ -n "$transcript" && -f "$transcript" ]]; then
  input_tokens=$(tac "$transcript" | jq -Rn '
    first(inputs | fromjson? | select(.type=="assistant"))
    | .message.usage
    | (.input_tokens//0) + (.cache_creation_input_tokens//0) + (.cache_read_input_tokens//0)
  ' 2>/dev/null)
  if [[ "$input_tokens" =~ ^[0-9]+$ ]] && ((input_tokens > limit)); then
    echo "Context at ${input_tokens} tokens (>${limit}) - run /session-handoff to capture the user's intent and what's left, then stop." >&2
    exit 2
  fi
fi
exit 0
