#!/bin/bash
WM_CLASS=$1

for id in $(wmctrl -l | awk '{print $1}'); do
  if xprop -id $id WM_CLASS | grep -q $WM_CLASS; then
    ID=$id
  fi
done

if [ -n "$ID" ]; then
  wmctrl -id -a $ID
fi

