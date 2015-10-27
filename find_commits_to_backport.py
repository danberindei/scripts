#!/bin/python

from subprocess import *
from pipes import quote
from tempfile import NamedTemporaryFile
from os import unlink
from sys import stderr, stdout

def run(cmd):
  stderr.write("Running %s\n" % cmd)
  return check_output(cmd, shell=True)

def lines(output):
  if output:
    return output.split('\n')
  else:
    return None

def diff(a, b):
  filea = NamedTemporaryFile(delete = False)
  filea.write(a)
  filea.close()
  fileb = NamedTemporaryFile(delete = False)
  fileb.write(b)
  fileb.close()

  try:
    return run("dwdiff -P -A best %s %s" % (filea.name, fileb.name))
  except CalledProcessError as e:
    #print("Error running command %s: %s" % (e.cmd, e.output))
    return e.output

  unlink(filea.name)
  unlink(fileb.name)

def main():
  pattern = "dan"
  subjects = lines(run("git log --reverse --format=format:'%%H %%ae %%ce %%s' jdg/jdg-6.3.x..master | awk '/%s/ { print $1; }' | git show --stdin --no-patch --no-walk --format=format:%%s" % pattern))

  # master = open("master.txt", "w")
  # prod = open("prod.txt", "w")

  i = 0
  dups = set()
  for subject in subjects:
    if subject in dups:
      continue

    dups.add(subject)
    mc = run("git log --reverse --format=format:'%%s' jdg/jdg-6.3.x..master | grep -F %s" % quote(subject))
    try:
      pc = run("git log --reverse --format=format:'%%s' master..jdg/jdg-6.3.x | grep -F %s" % quote(subject))
    except CalledProcessError as e:
      pc = None

    # master.write(mc + '\n')
    # if pc:
    #   prod.write(pc + '\n')
    #
    # for i in range(len(lines(mc)) - len(lines(pc))):
    #   prod.write("---\n")

    if not pc:
      for mcl in lines(mc):
        if mcl:
          stdout.write("+++ %s\n" % mcl)
    else:
      for dl in lines(diff(pc, mc)):
        if dl:
          stdout.write("    %s\n" % dl)

    i += 1
    # if i == 3 : break

  # master.close()
  # prod.close()

main()
