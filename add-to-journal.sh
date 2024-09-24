#!/bin/bash
set -euo pipefail

DATE=$(date +%Y-%m-%d)
TIMESTAMP=$(date +%Y-%m-%dT%H:%M:%S)
WINDOW_ID=$(dbus-send --session --dest=org.gnome.Shell --print-reply=literal /org/gnome/Shell/Extensions/Windows org.gnome.Shell.Extensions.Windows.List | jq '.[] | select(.focus) | .id')
DETAILS=$(dbus-send --session --dest=org.gnome.Shell --print-reply=literal /org/gnome/Shell/Extensions/Windows org.gnome.Shell.Extensions.Windows.Details uint32:$WINDOW_ID)
WM_CLASS=$(echo $DETAILS | jq -r .wm_class)
TITLE=$(echo $DETAILS | jq -r .title)
IDLE_MILLIS=$(dbus-send --print-reply --dest=org.gnome.Mutter.IdleMonitor /org/gnome/Mutter/IdleMonitor/Core org.gnome.Mutter.IdleMonitor.GetIdletime | sed -Ene 's/ *uint64 ([0-9]*)/\1/ p')

if [[ $# -gt 0 ]] ; then
	TEXT="$1"
else
	TEXT=$(zenity --title "Log" --text "$TITLE" --entry --entry-text "ping")
fi
JSON_TEXT=$(echo $TEXT | jq -R .)

echo $DETAILS | jq -c "{timestamp: \"$TIMESTAMP\", idle_seconds: ($IDLE_MILLIS/1000), wm_class, title, text: $JSON_TEXT}" >> ~/.local/share/jrnl/$DATE.jsonl
