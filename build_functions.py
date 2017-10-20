#!/bin/python

import re
import shlex
import signal

from os import chdir, environ, getcwd, path
from pipes import quote
from subprocess import *
from sys import argv, exit, stderr, stdout

debug = True

def run(cmd):
  return check_output(cmd, shell=True)

def print_and_run(cmd):
  stderr.write("### %s\n" % cmd)
  return check_call(cmd, shell=True)

def test(cmd):
  errcode = call(cmd, shell=True)
  #stderr.write("### %s -- %s\n" % (cmd, errcode))
  return errcode == 0

def filter_test_output(input):
  regex = re.compile("(?:^|(?<=\)))\[TestSuiteProgress\] (Tests succeeded: .*)$")

  line = input.readline()
  while line:
    m = regex.search(line)
    if m:
      # write the number of tests in the title
      stderr.write("\033]0;{0}\a".format(m.group(1)))

    stdout.write(line)
    line = input.readline()


def big_build_function(CLEAN_BUILD, BUILD, TEST):
    LOGS_DIR=getcwd() + "/../logs"

    # user options
    EXTRA_BUILD_OPTS=environ.get("EXTRA_BUILD_OPTS", "")
    EXTRA_TEST_OPTS=environ.get("EXTRA_TEST_OPTS", "")

    # maven options
    MAVEN_GENERIC_OPTS="-Dsurefire.skipAfterFailureCount=100"
    #MAVEN_TUNING_OPTS="-server -XX:+AggressiveOpts -XX:+UseCompressedOops -XX:+UseParallelOldGC -XX:NewRatio=3 -XX:+TieredCompilation"
    MAVEN_TUNING_OPTS="-server -XX:+AggressiveOpts -XX:+UseCompressedOops -XX:+UseG1GC -XX:MaxGCPauseMillis=500 -XX:+TieredCompilation -XX:+UseTransparentHugePages"
    #MAVEN_TUNING_OPTS="-server -XX:-UseCompressedOops -XX:+UseG1GC -XX:MaxGCPauseMillis=500 -XX:-TieredCompilation"
    #MAVEN_TUNING_OPTS=""
    #MAVEN_TUNING_OPTS="-server -XX:+AggressiveOpts -XX:+UseCompressedOops -XX:+UseConcMarkSweepGC -XX:+UseParNewGC -XX:NewRatio=4 -XX:-UseLargePages"
    #MAVEN_TUNING_OPTS="-server -XX:+UseCompressedOops -XX:+UseConcMarkSweepGC -XX:+UseParNewGC -XX:NewRatio=4"
    #MAVEN_MEMORY_OPTS="-Xmx1000m -XX:MaxPermSize=320m -Xss1m -XX:+HeapDumpOnOutOfMemoryError"
    MAVEN_MEMORY_OPTS="-Xmx1000m -Xss1m -XX:+HeapDumpOnOutOfMemoryError"
    #MAVEN_MEMORY_OPTS="-Xmx1500m -Xss1m"
    #FORK_MEMORY_OPTS="-Xmx2000m -Xss1m -XX:MaxPermSize=320m -XX:+HeapDumpOnOutOfMemoryError"
    FORK_MEMORY_OPTS="-Xmx2000m -Xss1m -XX:+HeapDumpOnOutOfMemoryError"
    MAVEN_JGROUPS_OPTS="-Djava.net.preferIPv4Stack=true -Djgroups.bind_addr=127.0.0.1"
    # for tests only
    #MAVEN_DEBUG_OPTS="-ea -agentlib:jdwp=transport=dt_socket,server=n,suspend=y,address=5006"
    MAVEN_DEBUG_OPTS="-ea -agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=5006"
    MAVEN_LOG_OPTS="-Dlog4j.configuration=file:/home/dan/Work/infinispan/log4j1-trace.xml"
    MAVEN_LOG_OPTS="-Dlog4j.configurationFile=file:///home/dan/Work/infinispan/log4j2-trace.xml -Dinfinispan.log.path=" + LOGS_DIR + " -DAsyncLogger.ThreadNameStrategy=UNCACHED " + MAVEN_LOG_OPTS
    MAVEN_GC_LOG_OPTS="-XX:+PrintGCTimeStamps -XX:+PrintGCApplicationStoppedTime -XX:+PrintGCDetails -Xloggc:/home/dan/Work/logs/gc.log"
    #MAVEN_GC_LOG_OPTS=""

    #MAVEN_OPTS=" ".join((MAVEN_TUNING_OPTS, MAVEN_JGROUPS_OPTS, EXTRA_BUILD_OPTS))

    if not environ.get("DEBUG_TESTS"):
      MAVEN_DEBUG_OPTS=""

    MAVEN_OPTS=" ".join((MAVEN_GENERIC_OPTS, MAVEN_TUNING_OPTS, MAVEN_MEMORY_OPTS, MAVEN_JGROUPS_OPTS, EXTRA_BUILD_OPTS))
    #MAVEN_FORK_OPTS=" ".join((MAVEN_OPTS, MAVEN_DEBUG_OPTS, EXTRA_TEST_OPTS))
    MAVEN_FORK_OPTS=" ".join((MAVEN_OPTS, MAVEN_LOG_OPTS, MAVEN_GC_LOG_OPTS, MAVEN_DEBUG_OPTS, EXTRA_TEST_OPTS))

    # check if the first parameter is a branch name - if yes, checkout that branch instead of copying the working dir
    if len(argv) > 1 and test("git rev-parse --abbrev-ref --verify -q %s" % argv[1]):
      BRANCH=argv[1]
      EXPLICIT_BRANCH=True
      remaining_args=argv[2:]
    else:
      #BRANCH=run("git symbolic-ref --short HEAD").strip()
      BRANCH=run("git name-rev --name-only HEAD").strip()
      EXPLICIT_BRANCH=False
      remaining_args=argv[1:]

    with open(LOGS_DIR + "/branch", "w") as f:
      f.write(BRANCH)

    PROJECT=path.basename(getcwd())
    print "Running off branch %s" % BRANCH

    DEST="../tmpbuild/%s" % quote(PROJECT)

    if EXPLICIT_BRANCH:
      if CLEAN_BUILD == 1:
        print_and_run("rm -rf %s" % quote(DEST))
        print_and_run("git clone -slb %s . %s" % (quote(BRANCH), quote(DEST)))
      else:
        stderr.write("Cannot test a custom branch without building and cleaning the directory\n")
        exit(2)
    else:
      rsync_delete = ""
      if CLEAN_BUILD == 1:
        rsync_delete = "--delete"
      print_and_run("mkdir -p %s" % quote(DEST))
      print_and_run("rsync -a %s --link-dest=. --exclude '.git' --exclude 'target' --exclude '*.log' . %s" % (rsync_delete, quote(DEST)))

    chdir(DEST)

    # try to parse as many arguments as possible as module names
    MODULE_ARGS=""
    while remaining_args and path.isdir(remaining_args[0]):
      if not MODULE_ARGS:
        MODULE_ARGS="-pl " + quote(remaining_args[0])
      else:
        MODULE_ARGS=MODULE_ARGS + "," + quote(remaining_args[0])
      remaining_args = remaining_args[1:]

    print "Building modules %s" % MODULE_ARGS
    EXTRA_ARGS=" ".join([quote(arg) for arg in remaining_args])
    print "Extra args %s" % EXTRA_ARGS

    ERRCODE=0
    if CLEAN_BUILD == 1:
      print_and_run("mvn -nsu clean -s maven-settings.xml %s" % EXTRA_ARGS)

    if BUILD == 1:
      print_and_run("mvn -nsu install -s maven-settings.xml -DskipTests -am %s %s" % (MODULE_ARGS, EXTRA_ARGS))

    if TEST == 1:
      print "MAVEN_FORK_OPTS=%s" % MAVEN_FORK_OPTS
      environ["MAVEN_FORK_OPTS"] = MAVEN_FORK_OPTS
      #cmd = "mvn -e -o surefire:test failsafe:integration-test failsafe:verify -Ptest-CI %s %s %s" %(MODULE_ARGS, MAVEN_LOG_OPTS, EXTRA_ARGS)
      #cmd = "mvn -o verify -Ptest-CI %s %s %s" %(MODULE_ARGS, MAVEN_LOG_OPTS, EXTRA_ARGS)
      cmd = "mvn -o verify -s maven-settings.xml %s %s %s" %(MODULE_ARGS, MAVEN_LOG_OPTS, EXTRA_ARGS)
      pipe = Popen(shlex.split(cmd), stdout = PIPE, stderr = STDOUT)

      try:
        filter_test_output(pipe.stdout)
        returncode = pipe.wait()
      except Exception as e:
        pipe.terminate()
        raise e

      if returncode != 0:
        raise CalledProcessError(returncode, cmd)


def main():
   print "JAVA_HOME=%s" % environ["JAVA_HOME"]

   script_name=path.basename(argv[0])
   if script_name == "cbuild":
     big_build_function(1, 1, 0)
   elif script_name == "jbuild":
     big_build_function(0, 1, 0)
   elif script_name == "jtest":
     big_build_function(0, 0, 1)
   elif script_name == "btest":
     big_build_function(0, 1, 1)
   elif script_name == "cbtest":
     big_build_function(1, 1, 1)
   else:
     raise Exception("Unrecognized executable name: %s" % script_name)


saved_path = getcwd()
try:
   main()
except KeyboardInterrupt:
   print "Interrupted!"
   exit(128 + signal.SIGINT)
except CalledProcessError as e:
   print e
   exit(10 + e.returncode)
finally:
   chdir(saved_path)
