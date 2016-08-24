#!/bin/bash

DIR=`dirname $0`
#echo dir=$DIR

FILE=$1 ; shift
FAILED_TESTS="$@"

CAT=cat
if [ "${FILE##*.}" == "gz" ] ; then
  CAT=zcat
fi

if [ ! -f "$FILE" ] ; then
  echo "Could not read file $FILE"
fi

echo Processing $FILE

if [ -z "$FAILED_TESTS" ] ; then
  if $CAT $FILE | head -100 | grep -q TestSuiteProgress ; then
    FAILED_TESTS=$($CAT $FILE | perl -ne '/\[TestSuiteProgress\] .* (?:failed|skipped): .*\.([^.]*)\.[^.]*/ && print "$1\n";' | sort -u)
  else
    FAILED_TESTS=$($CAT $FILE | perl -ne '/Test .*\(.*\.(.*)\) (failed|skipped)\./ && print "$1\n";' | sort -u)
  fi
fi
echo Failed/skipped tests: $FAILED_TESTS

if [ -f branch ] ; then
  BRANCH=_$(cat branch)
fi

DATE=$(date +%Y%m%d)
for TEST in $FAILED_TESTS ; do
  #SHORTNAME=`perl -e '$t = $ARGV[0]; chomp $t; $t =~ s/[-a-z]//g; print $t;' $TEST`
  #LOWSHORTNAME=`perl -e 'print lc $ARGV[0];' $SHORTNAME`
  TESTFILE=$(echo ${TEST}${BRANCH}_${DATE}.log | tr / _)
  TESTFILE=${TESTFILE//[^a-zA-Z0-9-_.]/}
  echo "Writing $TEST log to $TESTFILE"
  $CAT $FILE | $DIR/greplog.py "\(.*\b$TEST\b.*\) \[" | perl -npe "s/$TEST-Node/Node/g" > $TESTFILE
done
