#!/usr/bin/python

import fileinput
import re

tests = dict()
orphan_threads = dict()
previous_test = None
previous_orphan = None
pattern = re.compile("\(testng-([A-Za-z0-9.]+)")

for line in fileinput.input():
  m = pattern.search(line)
  if m:
    test_name = m.group(1)
    if test_name not in tests:
      tests[test_name] = 0
      #print("New test: %s" % test_name)

  test_matched = False
  for test_name in tests.keys():
    if test_name in line:
      tests[test_name] += 1
      test_matched = True
      previous_test = test_name
      previous_orphan = None
      break

  if test_matched:
    continue

  orphan_pattern = re.compile('(?:FATAL|ERROR|WARN |DEBUG|TRACE) \(([^\)]+)\)')
  m = orphan_pattern.search(line)
  if m:
    thread_name = m.group(1)
    if thread_name not in orphan_threads:
      orphan_threads[thread_name] = 1
    else:
      orphan_threads[thread_name] += 1
    previous_orphan = thread_name
    previous_test = None
    continue

  if previous_test:
    tests[previous_test] += 1
  elif previous_orphan:
    orphan_threads[previous_orphan] += 1


for test_name in sorted(tests, key=tests.__getitem__):
  count = tests[test_name]
  print("%7d %s" % (count, test_name))

for (orphan_thread_name, count) in orphan_threads.items():
  print("%7d orphan %s" % (count, orphan_thread_name))

