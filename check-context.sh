#!/usr/bin/env bash
# Claude Code UserPromptSubmit + PreToolUse hook (~/.claude/settings.json).
# Blocks when context exceeds the token limit and directs the agent to run /session-handoff.
# Register for BOTH events: only UserPromptSubmit sees .prompt, so without it the flag file is
# never armed and the session-handoff bypass below never fires.
limit=150000
handoff_skill=session-handoff

input=$(cat)
transcript=$(echo "$input" | jq -r '.transcript_path // empty')
prompt=$(echo "$input" | jq -r '.prompt // empty')
session_id=$(echo "$input" | jq -r '.session_id // empty')
tool_name=$(echo "$input" | jq -r '.tool_name // empty')
tool_skill=$(echo "$input" | jq -r '.tool_input.skill // empty')

if [[ -n "$session_id" ]]; then
  flag_file="/tmp/claude-${handoff_skill}-${session_id}"

  # Allow session-handoff invocations through regardless of context
  if [[ -n "$prompt" ]] && echo "$prompt" | grep -qi "$handoff_skill"; then
    touch "$flag_file"
    exit 0
  fi

  # Allow Skill tool calls invoking session-handoff through regardless of context
  if [[ "$tool_name" == "Skill" ]] && echo "$tool_skill" | grep -qi "$handoff_skill"; then
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
    echo "Context at ${input_tokens} tokens (>${limit}) - run /${handoff_skill} to capture the user's intent and what's left, then stop." >&2
    exit 2
  fi
fi
exit 0
