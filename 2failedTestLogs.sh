#!/bin/sh

DIR=`dirname $0`
CAT=cat
#echo dir=$DIR

if [ -f "$1" ] ; then FILE=$1 ; shift ; fi
if [ -n "$1" ] ; then FAILED_TESTS="$*" ; fi

if [ ! -f "$FILE" ] ; then
  FILE=infinispan.log
  if [ ! -f "$FILE" ] ; then
    ZFILE=infinispan.log.gz
    CAT=zcat
  fi
fi

if [ ! -f "$FILE" ] ; then
  echo "Could not open infinispan.log or infinispan.log.gz"
fi

echo Processing $FILE
export CAT FILE


if [ -z "$FAILED_TESTS" ] ; then
  FAILED_TESTS=`$CAT $FILE | egrep "UnitTestTestNGListener.*(failed|skipped)" | perl -ne '/Test .*\(.*\.(.*)\)/; print "$1\n";' | sort | uniq`
  #FAILED_TESTS=`$CAT $FILE | egrep "(Test failed)|(skipped.\$)" | perl -ne '/.*\(.*\.(.*)\)$/; print "$1\n";' | sort | uniq`
fi
echo Failed/skipped tests: $FAILED_TESTS 

echo greptest.py "$FILE" $FAILED_TESTS
greptest.py "$FILE" $FAILED_TESTS
