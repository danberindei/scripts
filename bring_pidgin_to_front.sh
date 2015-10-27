#!/bin/bash
WM_CLASS=$1

for id in $(wmctrl -l | awk '{print $1}'); do
  UNSEEN_COUNT=$(xprop -id $id _PIDGIN_UNSEEN_COUNT | grep -v "not found" | awk '{print $NF}')
  if [ -n "$UNSEEN_COUNT" ]; then
    ID=$id
    if [ "$UNSEEN_COUNT" -gt 0 ]; then
      UNSEEN_ID=$id
    fi
  fi
done

if [ -n "$UNSEEN_ID" ]; then
  wmctrl -id -a $UNSEEN_ID
elif [ -n "$ID" ]; then
  wmctrl -id -a $ID
fi

