#!/bin/sh

DIR=`dirname $0`
#echo dir=$DIR

if [ -r "$1" ] ; then FILE=$1 ; shift ; fi
if [ -n "$1" ] ; then FAILED_TESTS="$*" ; fi

if [ -z "$FILE" ] ; then
  FILE=`ls -t infinispan.log* | head -1`
fi

CAT=cat
if [ "${FILE##*.}" == "gz" ] ; then
  CAT=zcat
fi

if [ ! -f "$FILE" ] ; then
  echo "Could not find infinispan.log or infinispan.log.gz"
fi

echo Processing $FILE

if [ -z "$FAILED_TESTS" ] ; then
  FAILED_TESTS=`$CAT $FILE | perl -ne '/Test .*\(.*\.(.*)\) (failed|skipped)\./ && print "$1\n";' | sort -u`
fi
echo Failed/skipped tests: $FAILED_TESTS 

BRANCH=$(cat branch)

DATE=$(date +%Y%m%d)
for TEST in $FAILED_TESTS ; do
  #SHORTNAME=`perl -e '$t = $ARGV[0]; chomp $t; $t =~ s/[-a-z]//g; print $t;' $TEST`
  #LOWSHORTNAME=`perl -e 'print lc $ARGV[0];' $SHORTNAME`
  TESTFILE=$(echo ${TEST}_${BRANCH}_${DATE}.log | tr / _)
  echo "Writing $TEST log to $TESTFILE"
  $CAT $FILE | $DIR/greplog.py "\(.*\b$TEST\b.*\) \[" | perl -npe "s/$TEST-Node/Node/g" > $TESTFILE
done
