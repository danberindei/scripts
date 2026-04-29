#!/usr/bin/env bash
input=$(cat)
pct=$(printf '%s' "$input" | jq '.context_window.used_percentage // 0 | floor' 2>/dev/null)
[[ "$pct" =~ ^[0-9]+$ ]] && ((pct > 60)) && echo "Context at ${pct}% (>60%) - run /compact or start a new session." && exit 2
exit 0
