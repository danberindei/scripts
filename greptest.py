#!/usr/bin/python

from __future__ import print_function

import argparse
import mmap
import os
import re
import sys

message_start_pattern = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3} ", re.M)

def main():
   args = parse_args()
   file_name = args.file[0]
   tests = args.tests
   result_files = dict()
   test_patterns = dict()

   try:
      for test_name in tests:
         test_file_name = gen_file_name(test_name)
         print("Opening output file %s for %s" % (test_file_name, test_name))
         result_files[test_name] = open(test_file_name, "w")
         test_patterns[test_name] = re.compile(test_name)

      match_start = 0
      match_end = 0
      data = mmap_view(file_name)
      for m in log_message_iter(data):
         match_end = m.start()
         #print("Found match: %s:%s" % (match_start, match_end))
         message = data[match_start:match_end]
         match_start = match_end
         #print("Found log message %s" % message)
         match_message(message, test_patterns, result_files)

      message = data[match_start:]
      match_message(message, test_patterns, result_files)
   finally:
      for test_file in result_files.itervalues():
         test_file.close()

def match_message(message, test_patterns, result_files):
   for (test_name, test_pattern) in test_patterns.iteritems():
      if re.search(test_pattern, message):
         short_message = re.sub("(" + test_name + ")-Node", "Node", message)
         result_files[test_name].write(short_message)

def parse_args():
   parser = argparse.ArgumentParser("greptest.py")
   parser.add_argument('file', nargs=1,
                      help='Log file')
   parser.add_argument('tests', metavar='test', nargs='+',
                      help='Test names')
   args = parser.parse_args()
   #print(args)
   return args


def gen_file_name(test_name):
   return re.sub(r"[^A-Z0-9]", "", test_name).lower() + ".log"

def mmap_view(file_name):
   print("Opening input file %s" % file_name)
   f = open(file_name)
   if not f:
      print("Invalid input file: %s" % file_name)
      exit(1)

   size = os.stat(file_name).st_size
   if size > 2000000000:
     raise Exception("Log is too big")

   data = mmap.mmap(f.fileno(), size, access=mmap.ACCESS_READ)
   return data

def log_message_iter(data):
   return re.finditer(message_start_pattern, data)

if __name__ == "__main__":
  main()


