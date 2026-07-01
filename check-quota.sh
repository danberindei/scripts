#!/usr/bin/env bash
# Claude Code UserPromptSubmit + PreToolUse hook: block tool calls when quota pace is red.
# Register for BOTH events: UserPromptSubmit arms the bypass flag, PreToolUse checks quota.
# Uses the same algorithm as Paseo's getRateLimitWindowTone:
#   red when remainingPercent < expectedRemainingPercent * 0.5
#
# Caches the API response for 60s to avoid hammering the endpoint.
# User bypass: type "ignore quota", "continue in X min", or "snooze for Xh" to disable the check for that session.

bypass_pattern="ignore quota|continue in [0-9]+|snooze for [0-9.]+"

config_dir="${1:-${CLAUDE_CONFIG_DIR:-${HOME}/.claude}}"

CACHE_DIR="${XDG_RUNTIME_DIR:-${HOME}/.cache}/claude-pace"
CACHE_FILE="${CACHE_DIR}/quota-hook-cache-$(basename "$config_dir")"
CACHE_TTL=120
CREDENTIALS="${config_dir}/.credentials.json"
USAGE_URL="https://api.anthropic.com/api/oauth/usage"
BETA_HEADER="oauth-2025-04-20"

mkdir -p "$CACHE_DIR" 2>/dev/null

input=$(cat)
session_id=$(echo "$input" | jq -r '.session_id // empty')
prompt=$(echo "$input" | jq -r '.prompt // empty')

if [[ -n "$session_id" ]]; then
  flag_file="/tmp/claude-bypass-quota-${session_id}"

  # UserPromptSubmit: arm the bypass flag if the user typed the keyword.
  if [[ -n "$prompt" ]] && echo "$prompt" | grep -Ei "$bypass_pattern"; then
    touch "$flag_file"
    exit 0
  fi

  # PreToolUse: skip quota check if bypass is armed.
  if [[ -f "$flag_file" ]]; then
    exit 0
  fi
fi

now_s=$(date +%s)
now_ms=$((now_s * 1000))

# Read cached response if fresh enough.
body=""
if [ -f "$CACHE_FILE" ]; then
  cache_age=$((now_s - $(stat -c%Y "$CACHE_FILE" 2>/dev/null || stat -f%m "$CACHE_FILE" 2>/dev/null || echo 0)))
  if [ "$cache_age" -le "$CACHE_TTL" ]; then
    body=$(cat "$CACHE_FILE")
  fi
fi

# Fetch if cache is stale or missing.
if [ -z "$body" ]; then
  [ -f "$CREDENTIALS" ] || exit 0
  token=$(jq -r '.claudeAiOauth.accessToken // empty' "$CREDENTIALS" 2>/dev/null)
  [ -n "$token" ] || exit 0

  body=$(curl -sf --max-time 5 \
    -H "Authorization: Bearer ${token}" \
    -H "anthropic-beta: ${BETA_HEADER}" \
    "$USAGE_URL" 2>/dev/null) || exit 0
  [ -n "$body" ] || exit 0
  printf '%s' "$body" > "$CACHE_FILE"
fi

# Check each window. Exit 2 (block) if any is "red".
# jq outputs lines of: utilization resets_at_epoch window_duration_ms label
check=$(echo "$body" | jq -r --argjson now "$now_ms" '
  def check_window(key; dur_ms):
    .[key] // null
    | if . == null then empty
      else
        (.utilization // null) as $util |
        (.resets_at // null) as $resets_at_str |
        if $util == null or $resets_at_str == null then empty
        else
          ($resets_at_str | sub("\\.[0-9]+.*$"; "Z") | fromdateiso8601 * 1000) as $reset_ms |
          if $reset_ms <= $now then empty
          else
            (100 - $util) as $remaining |
            (dur_ms - ([$reset_ms - $now, 0] | max)) as $elapsed_ms |
            ($elapsed_ms / dur_ms) as $elapsed_frac |
            if $elapsed_frac <= 0 then empty
            else
              ((1 - $elapsed_frac) * 100) as $expected_remaining |
              ($expected_remaining * 0.5) as $red_threshold |
              if $remaining < $red_threshold then
                "\(key): \($remaining | round)% left, expected \($expected_remaining | round)%"
              else empty
              end
            end
          end
        end
      end;
  check_window("five_hour"; 5*60*60*1000),
  check_window("seven_day"; 7*24*60*60*1000),
  check_window("seven_day_opus"; 7*24*60*60*1000),
  check_window("seven_day_sonnet"; 7*24*60*60*1000)
')

if [ -n "$check" ]; then
  echo "Quota pace is red -- stop and wait for reset." >&2
  echo "$check" >&2
  exit 2
fi

exit 0
