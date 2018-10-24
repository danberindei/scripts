#!/bin/bash

#Alpha
for f in ?????????????.pdf ; do
  NEW_NAME="$(pdftotext "$f" - | perl ~/bin/alpha_statement_name.pl)"
  if [ ${#NEW_NAME} -gt 5 ] ; then
    if [ ! -e "${NEW_NAME}.pdf" ] ; then
      echo mv "$f" "${NEW_NAME}.pdf"
      mv "$f" "${NEW_NAME}.pdf"
    fi
  fi
done

#BT
for f in *RO*BTRL*.pdf ; do
  NEW_NAME="$(pdftotext "$f" - | perl ~/bin/bt_statement_name.pl)"
  if [ ${#NEW_NAME} -gt 5 ] ; then
    if [ ! -e "${NEW_NAME}.pdf" ] ; then
      echo mv "$f" "${NEW_NAME}.pdf"
      mv "$f" "${NEW_NAME}.pdf"
    fi
  fi
done
