#!/bin/python

import re
import shlex
import signal

from subprocess import *
from os import chdir, environ, getcwd, path
from pipes import quote
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
  regex = re.compile("Tests succeeded:")
  regex2 = re.compile("Test (starting|succeeded):")
  line = input.readline()
  while line:
    if regex.search(line):
      # write the number of tests in the title
      #stdout.write("\033]0;%s" % (line))
      # go to top-left corner: "\033[s\033[1;1H" and back: "\033[u"
      # go up 1 line
      stdout.write("\033[A")
      stdout.write(line.replace("\n", "\033[K\n"))
    elif regex2.search(line):
      stdout.write(line.replace("\n", "\033[K\r"))
    else:
      stdout.write(line.replace("\n", "\033[K\n"))

    line = input.readline()


def big_build_function(CLEAN_BUILD, BUILD, TEST):
    LOGS_DIR=getcwd() + "/../logs"

    # user options
    EXTRA_BUILD_OPTS=environ.get("EXTRA_BUILD_OPTS", "")
    EXTRA_TEST_OPTS=environ.get("EXTRA_TEST_OPTS", "")

    # maven options
    #MAVEN_TUNING_OPTS="-server -XX:+AggressiveOpts -XX:+UseCompressedOops -XX:+UseParallelOldGC -XX:NewRatio=3 -XX:+TieredCompilation"
    MAVEN_TUNING_OPTS="-server -XX:+AggressiveOpts -XX:+UseCompressedOops -XX:+UseG1GC -XX:MaxGCPauseMillis=500 -XX:+TieredCompilation"
    #MAVEN_TUNING_OPTS="-server -XX:-UseCompressedOops -XX:+UseG1GC -XX:MaxGCPauseMillis=500 -XX:-TieredCompilation"
    #MAVEN_TUNING_OPTS=""
    #MAVEN_TUNING_OPTS="-server -XX:+AggressiveOpts -XX:+UseCompressedOops -XX:+UseConcMarkSweepGC -XX:+UseParNewGC -XX:NewRatio=4 -XX:-UseLargePages"
    #MAVEN_TUNING_OPTS="-server -XX:+UseCompressedOops -XX:+UseConcMarkSweepGC -XX:+UseParNewGC -XX:NewRatio=4"
    #MAVEN_MEMORY_OPTS="-Xmx1000m -XX:MaxPermSize=320m -Xss1m -XX:+HeapDumpOnOutOfMemoryError"
    MAVEN_MEMORY_OPTS="-Xmx1500m -Xss1m"
    FORK_MEMORY_OPTS="-Xmx2000m -Xss1m"
    MAVEN_JGROUPS_OPTS="-Djava.net.preferIPv4Stack=true -Djgroups.bind_addr=127.0.0.1"
    # for tests only
    MAVEN_DEBUG_OPTS="-ea -agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=5006"
    MAVEN_LOG_OPTS="-Dlog4j.configuration=file:/home/dan/Work/infinispan/log4j-trace.xml"
    MAVEN_LOG_OPTS="-Dlog4j.configurationFile=file:///home/dan/Work/infinispan/log4j2-trace.xml -Dinfinispan.log.path=" + LOGS_DIR + " " + MAVEN_LOG_OPTS
    #MAVEN_GC_LOG_OPTS="-XX:+PrintGCTimeStamps -XX:+PrintGCApplicationStoppedTime -XX:+PrintGCDetails -Xloggc:/home/dan/Work/logs/gc.log"
    MAVEN_GC_LOG_OPTS=""

    #MAVEN_OPTS=" ".join((MAVEN_TUNING_OPTS, MAVEN_JGROUPS_OPTS, EXTRA_BUILD_OPTS))

    if not environ.get("MAVEN_DEBUG"):
      MAVEN_DEBUG_OPTS=""

    MAVEN_OPTS=" ".join((MAVEN_TUNING_OPTS, MAVEN_MEMORY_OPTS, MAVEN_JGROUPS_OPTS, EXTRA_BUILD_OPTS))
    #MAVEN_FORK_OPTS=" ".join((MAVEN_OPTS, MAVEN_DEBUG_OPTS, EXTRA_TEST_OPTS))
    MAVEN_FORK_OPTS=" ".join((MAVEN_OPTS, MAVEN_LOG_OPTS, MAVEN_GC_LOG_OPTS, MAVEN_DEBUG_OPTS, EXTRA_TEST_OPTS))

    # check if the first parameter is a branch name - if yes, checkout that branch instead of copying the working dir
    if len(argv) > 1 and test("git rev-parse --abbrev-ref --verify -q %s" % argv[1]):
      BRANCH=argv[1]
      EXPLICIT_BRANCH=True
      remaining_args=argv[2:]
    else:
      BRANCH=run("git symbolic-ref --short HEAD").strip()
      EXPLICIT_BRANCH=False
      remaining_args=argv[1:]

    with open(LOGS_DIR + "/branch", "w") as f:
      f.write(BRANCH)

    PROJECT=path.basename(getcwd())
    print "Running off branch %s" % BRANCH
    UPSTREAM_BRANCH=run("find_upstream_branch %s" % quote(BRANCH))
    #DEST="/tmp/privatebuild/%s/%s" % (quote(PROJECT), quote(UPSTREAM_BRANCH))
    DEST="/tmp/privatebuild/%s" % quote(PROJECT)
    #DEST="../privatebuild/%s" % quote(PROJECT)

    if not UPSTREAM_BRANCH:
      exit(1)

    if EXPLICIT_BRANCH:
      if CLEAN_BUILD == 1:
        print_and_run("rm -rf %s" % quote(DEST))
        print_and_run("git clone -slb %s . %s" % (quote(BRANCH), quote(DEST)))
      else:
        stderr.write("Cannot test a custom branch without building and cleaning the directory\n")
        exit(2)
    else:
      print_and_run("mkdir -p %s" % quote(DEST))
      print_and_run("rsync -a --delete --link-dest=. --exclude '.git' --exclude 'target' --exclude '*.log' . %s" % quote(DEST))

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
      #print_and_run mvn -nsu clean -am ${=MODULE_ARGS}
      print_and_run("mvn -nsu clean %s" % EXTRA_ARGS)

    if BUILD == 1:
      #print_and_run mvn -nsu -P-extras $CLEAN install -DskipTests -am ${=MODULE_ARGS} ${=EXTRA_ARGS}
      print_and_run("mvn -nsu install -DskipTests -am %s %s" % (MODULE_ARGS, EXTRA_ARGS))

    if TEST == 1:
      print "MAVEN_FORK_OPTS=%s" % MAVEN_FORK_OPTS
      environ["MAVEN_FORK_OPTS"] = MAVEN_FORK_OPTS
      #cmd = "mvn -e -o surefire:test failsafe:integration-test failsafe:verify -Ptest-CI %s %s %s" %(MODULE_ARGS, MAVEN_LOG_OPTS, EXTRA_ARGS)
      cmd = "mvn -e -o verify -Ptest-CI %s %s %s" %(MODULE_ARGS, MAVEN_LOG_OPTS, EXTRA_ARGS)
      pipe = Popen(shlex.split(cmd), stdout = PIPE, stderr = STDOUT)
      filter_test_output(pipe.stdout)
      returncode = pipe.wait()
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
