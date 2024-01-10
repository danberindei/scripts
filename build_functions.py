#!/bin/python -u

import datetime
import re
import shlex
import signal
import subprocess

from os import chdir, environ, getcwd, path, listdir
from pipes import quote
from sys import argv, exit, stderr, stdout

DEBUG = True
MVN = environ.get('MVN', 'mvnd')
CLEAN_BUILD = False
BUILD = False
TEST = False

def run(cmd):
    return subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True).stdout

def print_and_run(cmd):
    stderr.write("### %s\n" % cmd)
    subprocess.run(cmd, shell=True, check=True)

def test(cmd):
    errcode = subprocess.run(cmd, shell=True).returncode
    #stderr.write("### %s -- %s\n" % (cmd, errcode))
    return errcode == 0

def filter_test_output(input, logfile):
    regex = re.compile(r"(\[OK:\s*\d*, KO:\s*\d*, SKIP:\s*\d*\]).*$")

    prev_line_matched = False
    line = input.readline().decode()
    while line:
        if logfile:
            logfile.write(line)
        m = regex.search(line)
        out_line = line
        if m:
            line = line.replace("org.infinispan", "o.i")
            # write the number of tests in the title
            stderr.write("\033]0;%s\a" % m.group(1))
            if prev_line_matched:
                # overwrite the previous line
                out_line = "\033[F%s \033[K\n" % line.rstrip("\n")

        stdout.write(out_line)

        prev_line_matched = bool(m)
        line = input.readline().decode()


def big_build_function():
        BUILD_DIR=environ.get("PROJECT_DIR")
        if not BUILD_DIR or not path.isdir(BUILD_DIR):
            print("Invalid $PROJECT_DIR: %s" % BUILD_DIR)
            exit(1)

        # check if the first parameter is a branch name - if yes, checkout that branch instead of copying the working dir
        if len(argv) > 1 and test("git -C %s rev-parse --abbrev-ref --verify -q %s" % (quote(BUILD_DIR), argv[1])):
            BRANCH=str(argv[1])
            EXPLICIT_BRANCH=True
            remaining_args=argv[2:]
        else:
            #BRANCH=run("git symbolic-ref --short HEAD").strip()
            BRANCH=run("git -C %s name-rev --name-only HEAD" % quote(BUILD_DIR)).strip()
            EXPLICIT_BRANCH=False
            remaining_args=argv[1:]

        SAFE_BRANCH=re.sub("[^a-zA-Z0-9=-]", "_", BRANCH)
        DATE=datetime.datetime.today().strftime("%Y%m%d-%H%M")
        LOGS_DIR=BUILD_DIR + "/../logs"
        #LOGS_DIR=BUILD_DIR + "/../logs/" + SAFE_BRANCH + "_" + DATE
        #print_and_run("mkdir -p %s" % quote(LOGS_DIR))

        # user options
        EXTRA_BUILD_OPTS=environ.get("EXTRA_BUILD_OPTS", "")
        EXTRA_TEST_OPTS=environ.get("EXTRA_TEST_OPTS", "")

        # maven options
        MAVEN_GENERIC_OPTS="-Dsun.zip.disableMemoryMapping=true"
        #MAVEN_TUNING_OPTS="-server -XX:+AggressiveOpts -XX:+UseCompressedOops -XX:-TieredCompilation -XX:+UseTransparentHugePages"
        #MAVEN_TUNING_OPTS="-server -XX:+AggressiveOpts -XX:+UseCompressedOops -XX:+UseConcMarkSweepGC -XX:+UseParNewGC -XX:NewRatio=4 -XX:-UseLargePages"
        #MAVEN_TUNING_OPTS="-server -XX:+AggressiveOpts -XX:+UseCompressedOops -XX:+UseG1GC -XX:MaxGCPauseMillis=500 -XX:-TieredCompilation -XX:+UseTransparentHugePages"
        #MAVEN_TUNING_OPTS="-XX:+UseTransparentHugePages -XX:+UseLargePagesInMetaspace"
        MAVEN_TUNING_OPTS="-XX:+UseTransparentHugePages"
        #MAVEN_TUNING_OPTS=""
        #MAVEN_MEMORY_OPTS="-Xmx1000m -XX:MaxPermSize=320m -Xss1m -XX:+HeapDumpOnOutOfMemoryError"
        MAVEN_MEMORY_OPTS="-Xmx700m -Xss1m -XX:+HeapDumpOnOutOfMemoryError -XX:NativeMemoryTracking=detail"
        #MAVEN_MEMORY_OPTS="-Xmx1500m -Xss1m"
        # for tests only
        #FORK_MEMORY_OPTS="-Xmx2000m -Xss1m -XX:MaxPermSize=320m -XX:+HeapDumpOnOutOfMemoryError"
        # -XX:NativeMemoryTracking=detail
        FORK_MEMORY_OPTS="-Xmx1000m -Xss1m -XX:+HeapDumpOnOutOfMemoryError -XX:NativeMemoryTracking=detail"
        MAVEN_JGROUPS_OPTS="-Djava.net.preferIPv4Stack=true -Djgroups.bind_addr=127.0.0.1"
        MAVEN_LOG_ARGS=""
        #MAVEN_LOG_OPTS=MAVEN_LOG_OPTS + "-Dlog4j.configuration=file:/home/dan/Work/infinispan/log4j1-trace.xml"
        #MAVEN_LOG_OPTS=MAVEN_LOG_OPTS + "-Dlog4j.configurationFile=file:///home/dan/Work/infinispan/log4j2-trace.xml "
        MAVEN_LOG_ARGS=MAVEN_LOG_ARGS + " -Dlog4j.configuration=file://" + BUILD_DIR + "/log4j-trace.xml"
        MAVEN_LOG_ARGS=MAVEN_LOG_ARGS + " -Dlog4j.configurationFile=file://" + BUILD_DIR + "/log4j2-trace.xml"
        # MAVEN_LOG_OPTS=MAVEN_LOG_OPTS + " -Dinfinispan.log.path=" + LOGS_DIR + " -DAsyncLogger.ThreadNameStrategy=UNCACHED"
        MAVEN_GC_LOG_OPTS=""
        #MAVEN_GC_LOG_OPTS="-XX:+PrintGCDateStamps -XX:+PrintGCApplicationStoppedTime -XX:+PrintGCDetails -Xloggc:" + LOGS_DIR + "gc.log"


        if environ.get("DEBUG_TESTS") == "y":
            MAVEN_DEBUG_OPTS="-Dmaven.surefire.debug='-agentlib:jdwp=transport=dt_socket,server=n,suspend=y,address=5005' -Dmaven.failsafe.debug='-agentlib:jdwp=transport=dt_socket,server=n,suspend=y,address=5005'"
        elif environ.get("DEBUG_TESTS"):
            print("Invalid value for DEBUG_TESTS: %s. Only valid value is 'y'." % environ.get("DEBUG_TESTS"))
            exit(1)
        else:
            MAVEN_DEBUG_OPTS=""


        MAVEN_LOG_BRANCH_OPTS="-Dbuild.branch=" + SAFE_BRANCH
        #with open(LOGS_DIR + "/branch", "w") as f:
        #    f.write(BRANCH)

        MAVEN_OPTS=" ".join((MAVEN_GENERIC_OPTS, MAVEN_TUNING_OPTS, MAVEN_MEMORY_OPTS, EXTRA_BUILD_OPTS))
        MAVEN_FORK_OPTS=" ".join((MAVEN_GENERIC_OPTS, MAVEN_TUNING_OPTS, FORK_MEMORY_OPTS, MAVEN_JGROUPS_OPTS,
                                  MAVEN_LOG_ARGS, MAVEN_LOG_BRANCH_OPTS, MAVEN_GC_LOG_OPTS, EXTRA_TEST_OPTS))

        print("Running off branch %s" % BRANCH)

        DEST=path.abspath(".")

        rsync_delete = ""
        if CLEAN_BUILD == 1:
            current_files = listdir(DEST)
            assert not current_files or 'pom.xml' in current_files
            rsync_delete = "--delete --delete-excluded"
        #print_and_run("rsync -a %s --link-dest=%s --exclude 'target' --exclude '*.log' %s/. %s" % (rsync_delete, quote(BUILD_DIR), quote(BUILD_DIR), quote(DEST)))
        #print_and_run("rsync -a %s --exclude 'target' --exclude '*.log' %s/. %s" % (rsync_delete, quote(BUILD_DIR), quote(DEST)))
        print_and_run("rsync -a %s --exclude 'target' %s/. %s" % (rsync_delete, quote(BUILD_DIR), quote(DEST)))

        chdir(DEST)

        if EXPLICIT_BRANCH:
            if CLEAN_BUILD == 1:
                print_and_run("git reset --hard")
                print_and_run("git checkout %s" % (quote(BRANCH)))
            else:
                stderr.write("Cannot test a custom branch without building and cleaning the directory\n")
                exit(2)

        # try to parse as many arguments as possible as module names
        MODULE_ARGS=""
        while remaining_args and path.isdir(remaining_args[0]):
            if not MODULE_ARGS:
                MODULE_ARGS="-pl " + quote(remaining_args[0])
            else:
                MODULE_ARGS=MODULE_ARGS + "," + quote(remaining_args[0])
            remaining_args = remaining_args[1:]

        print("Building modules %s" % MODULE_ARGS)
        EXTRA_ARGS=" ".join([quote(arg) for arg in remaining_args])
        print("Extra args %s" % EXTRA_ARGS)

        print("MAVEN_OPTS=%s" % MAVEN_OPTS)
        environ["MAVEN_OPTS"] = MAVEN_OPTS

        if CLEAN_BUILD == 0:
            print_and_run("find . -path '*target*.log*' -delete")

        if BUILD == 1:
            print_and_run("%s -nsu install -s maven-settings.xml -DskipTests -am %s %s" % (MVN, MODULE_ARGS, EXTRA_ARGS))

        if TEST == 1:
            print("MAVEN_FORK_OPTS=%s" % MAVEN_FORK_OPTS)
            environ["MAVEN_FORK_OPTS"] = MAVEN_FORK_OPTS
            #MAVEN_TEST_ARGS = "-PtraceTests -P!extras -Dcheckstyle.skip=true -Dmodule.skipMavenRemoteResource=true"
            MAVEN_TEST_ARGS = "-Dcheckstyle.skip=true -Dmodule.skipMavenRemoteResource=true -Djboss.modules.settings.xml.url=file://%s/maven-settings.xml" % (BUILD_DIR)

            #cmd = "mvn -e -o surefire:test failsafe:integration-test failsafe:verify -Ptest-CI %s %s %s" %(MODULE_ARGS, MAVEN_LOG_OPTS, EXTRA_ARGS)
            test_mvn = "mvnd -1" if MVN == "mvnd" else MVN
            cmd = "%s -nsu verify -s maven-settings.xml %s %s %s %s %s" % (test_mvn, MODULE_ARGS, MAVEN_DEBUG_OPTS, MAVEN_TEST_ARGS, MAVEN_LOG_ARGS, EXTRA_ARGS)
            pipe = subprocess.Popen(shlex.split(cmd), stdout = subprocess.PIPE, stderr = subprocess.STDOUT)
            logfile = open("%s/build-%s.log" % (LOGS_DIR, DATE), "w")

            try:
                filter_test_output(pipe.stdout, logfile)
                returncode = pipe.wait()
            except Exception as e:
                pipe.terminate()
                raise e

            if path.isfile("%s/bin/process_trace_logs.sh" % BUILD_DIR):
                # Move the non-failed test logs to a subdirectory instead of deleting them
                print_and_run("mkdir -p logs")
                environ["DELETE_COMMAND"]="mv -t logs"
                print_and_run("%s/bin/process_trace_logs.sh %s %s/%s_%s_" % (BUILD_DIR, getcwd(), LOGS_DIR, BRANCH, DATE))
                print_and_run("find %s -name 'test-failures-*' | xargs -I@ sh -c 'mv @ %s/%s_%s_$(basename @)'" % (DEST, LOGS_DIR, BRANCH, DATE))
                print_and_run("find %s -name 'threaddump-*' | xargs -I@ sh -c 'mv @ %s/%s_%s_$(basename @)'" % (DEST, LOGS_DIR, BRANCH, DATE))
                chdir(LOGS_DIR)
                print_and_run("cleanTestLog.sh %s/%s_%s_*Test*.log.gz" % (LOGS_DIR, BRANCH, DATE))

            if returncode != 0:
                exit(returncode)


def main():
     global MVN, CLEAN_BUILD, BUILD, TEST 
     print("JAVA_HOME=%s" % environ["JAVA_HOME"])

     script_name=path.basename(argv[0])
     if script_name == "cbuild":
         CLEAN_BUILD = True
         BUILD = True
     elif script_name == "jbuild":
         BUILD = True
     elif script_name == "jtest":
         TEST = True
     elif script_name == "btest":
         BUILD = True
         TEST = True
     elif script_name == "cbtest":
         CLEAN_BUILD = True
         BUILD = True
         TEST = True
     else:
         raise Exception("Unrecognized executable name: %s" % script_name)

     big_build_function()

saved_path = getcwd()
try:
     main()
except KeyboardInterrupt:
     print("Interrupted!")
     exit(128 + signal.SIGINT)
except subprocess.CalledProcessError as e:
     print(e)
     exit(10 + e.returncode)
finally:
     chdir(saved_path)
