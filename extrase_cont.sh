#!/bin/bash

SCRIPT_DIR=$(dirname $0)

#Alpha
for f in ?????????????.pdf ????????-????????*.pdf ; do
  NEW_NAME="$(pdftotext "$f" - | perl $SCRIPT_DIR/alpha_statement_name.pl)"
  if [ ${#NEW_NAME} -gt 10 ] ; then
    if [ ! -e "${NEW_NAME}.pdf" ] ; then
      echo mv "$f" "${NEW_NAME}.pdf"
      mv "$f" "${NEW_NAME}.pdf"
    fi
  fi
done

#BT
for f in *RO*BTRL*.pdf statement*.pdf; do
  NEW_NAME="$(pdftotext "$f" - | perl $SCRIPT_DIR/bt_statement_name.pl)"
  if [ ${#NEW_NAME} -gt 10 ] ; then
    if [ ! -e "${NEW_NAME}.pdf" ] ; then
      echo mv "$f" "${NEW_NAME}.pdf"
      mv "$f" "${NEW_NAME}.pdf"
    fi
  fi
done
