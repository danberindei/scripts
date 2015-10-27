#!/usr/bin/python

from __future__ import print_function
import fileinput
import re

stacks = dict()
thread_name_pattern = re.compile('^".*')
stack_line_pattern = re.compile("\tat .*")
current_thread = None
current_stack = ""

for line in fileinput.input():
   if line == "\n":
      if current_thread:
         stacks.setdefault(current_stack, []).append(current_thread)

   if thread_name_pattern.match(line):
      current_thread = line
      current_stack = ""

   if stack_line_pattern.match(line):
      current_stack = current_stack + line;

for (stack, threads) in stacks.iteritems():
   threads.sort()
   for thread in threads:
      print(thread, end = '')
   print(stack)
