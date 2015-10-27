#!/usr/bin/python

from __future__ import print_function

import fileinput
import re

commit = ''
tests = dict()
headersPrinted = False

f = fileinput.input()
for line in f:
  if re.search('Testing commit', line):
    if commit and not headersPrinted:
      print('commit\tmessage', '\t'.join(tests.keys()), sep='\t')
      headersPrinted = True

    if tests:
      print(commit, '\t'.join(tests.values()), sep='\t')

    tests.clear()

  m = re.search('Testing commit (\w{40}) (.*)$', line)
  if m:
    commit = m.group(1) + '\t' + m.group(2)

  m = re.match('([0-9.]+) [a-zA-Z.]+ (\w+)', line)
  if m:
    tests[m.group(2)] = m.group(1)

if tests:
  print(commit, '\t'.join(tests.values()), sep='\t')

