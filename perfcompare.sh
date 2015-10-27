#!/bin/bash

BRANCH=t_ISPN-5019

function log() {
  echo $(date +%H:%M:%S) $* | tee -a perfcompare.log
}

log "Starting perf comparison on branch $BRANCH"
#mvn clean install -DskipTests -am -pl core || exit $?

for c in $(git log --format=%H master..$BRANCH); do
  log "Testing commit $c $(git log --format=%s -1 $c)"
  git checkout $c
  timeout 600 mvn clean install -pl core -DdefaultTestGroup=stress -DdefaultExcludedTestGroup= -Dtest=LargeClusterStressTest | tee >(grep 'Tests run: .* Time elapsed:' >> perfcompare.log) || exit $?
  find core -name 'TEST-*.xml' | xargs grep "<testcase" | sed 's/.*<testcase.* name="\([^"]*\)" .*/\1 &/' | sed 's/.*<testcase.* classname="\([^"]*\)".*/\1 &/' | sed 's/.*<testcase.* time="\([^"]*\)".*/\1 &/' | sed 's/ <testcase.*//' | tee -a perfcompare.log
done

log "Perf comparison done"
git checkout $BRANCH

