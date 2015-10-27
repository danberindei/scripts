#!/bin/sh

find $1 -name 'TEST-*.xml' | xargs grep -h "<testcase" | sed 's/.*<testcase.* name="\([^"]*\)".*/\1 &/' | sed 's/.*<testcase.* classname="\([^"]*\)".*/\1 &/' | sed 's/.*<testcase.* time="\([^"]*\)".*/\1 &/' | sort -rn | head -20
