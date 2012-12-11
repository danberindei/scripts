#!/usr/bin/python

from __future__ import print_function

import argparse
import mmap
import os
import re
import sys

message_start_pattern = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3} (?:FATAL|ERROR|WARN|INFO|DEBUG|TRACE)", re.M)

def main():
   args = parse_args()
   file_name = args.file[0]
   tests = args.tests
   result_files = dict()

   try:
      for test_name in tests:
         test_file_name = gen_file_name(test_name)
         print("Opening output file %s for %s" % (test_file_name, test_name))
         result_files[test_name] = open(test_file_name, "w")

      for m in log_message_iter(file_name):
         message = m.group(0)
         #print("Found log message %s" % message)
         for test_name in tests:
            if test_name in message:
               result_files[test_name].write(message)
   finally:
      for test_file in result_files.itervalues():
         test_file.close()

def parse_args():
   parser = argparse.ArgumentParser("Filter logs")
   parser.add_argument('file', nargs=1,
                      help='Log file')
   parser.add_argument('tests', metavar='test', nargs='+',
                      help='Test names')
   args = parser.parse_args()
   #print(args)
   return args


def gen_file_name(test_name):
   return re.sub(r"[a-z]", "", test_name).lower()


def log_message_iter(file_name):
   print("Opening input file %s" % file_name)
   f = open(file_name)
   if not f:
      print("Invalid input file: %s" % file_name)
      exit(1)

   size = os.stat(file_name).st_size
   data = mmap.mmap(f.fileno(), size, access=mmap.ACCESS_READ)

   return re.finditer(message_pattern, data)


main()


