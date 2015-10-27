#!/bin/zsh

function print() {
  echo \#\#\# $* >&2
}

function print_and_run() {
  print $*
  CMD=$1 ; shift
  $CMD ${=*}
  if [ $? -ne 0 ] ; then
    return 9
  fi
}

function big_build_function() {
    # maven options
#    MAVEN_TUNING_OPTS="-server -XX:+AggressiveOpts -XX:+UseCompressedOops -XX:+UseParallelOldGC -XX:NewRatio=3 -XX:+TieredCompilation"
    MAVEN_TUNING_OPTS="-server -XX:+AggressiveOpts -XX:+UseCompressedOops -XX:+UseG1GC -XX:MaxGCPauseMillis=500 -XX:+TieredCompilation"
    #MAVEN_TUNING_OPTS="-server -XX:+AggressiveOpts -XX:+UseCompressedOops -XX:+UseConcMarkSweepGC -XX:+UseParNewGC -XX:NewRatio=4 -XX:-UseLargePages"
    #MAVEN_TUNING_OPTS="-server -XX:+UseCompressedOops -XX:+UseConcMarkSweepGC -XX:+UseParNewGC -XX:NewRatio=4"
    MAVEN_MEMORY_OPTS="-Xmx1500m -XX:MaxPermSize=320m -Xss1m -XX:+HeapDumpOnOutOfMemoryError"
    MAVEN_JGROUPS_OPTS="-Djava.net.preferIPv4Stack=true -Djgroups.bind_addr=127.0.0.1"
    # for tests only
    MAVEN_DEBUG_OPTS="-ea -agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=5006"
    MAVEN_LOG_OPTS="-Dlog4j.configuration=file:/home/dan/Work/infinispan/log4j-trace.xml"
    MAVEN_LOG_OPTS="-Dlog4j.configurationFile=file:///home/dan/Work/infinispan/log4j2-trace.xml $MAVEN_LOG_OPTS"
    #MAVEN_GC_LOG_OPTS="-XX:+PrintGCTimeStamps -XX:+PrintGCApplicationStoppedTime -XX:+PrintGCDetails"

    #MAVEN_OPTS="$MAVEN_TUNING_OPTS $MAVEN_JGROUPS_OPTS $EXTRA_BUILD_OPTS"

    LOGS_DIR=`pwd`/../logs

    CLEAN_BUILD=$1 ; shift
    BUILD=$1 ; shift
    TEST=$1 ; shift

    if [ -z "$MAVEN_DEBUG" ] ; then
      MAVEN_DEBUG_OPTS=""
    fi
    MAVEN_OPTS="$MAVEN_TUNING_OPTS $MAVEN_MEMORY_OPTS $MAVEN_JGROUPS_OPTS $EXTRA_BUILD_OPTS"
    #MAVEN_FORK_OPTS="$MAVEN_OPTS $MAVEN_DEBUG_OPTS $EXTRA_TEST_OPTS "
    MAVEN_FORK_OPTS="$MAVEN_OPTS $MAVEN_LOG_OPTS $MAVEN_GC_LOG_OPTS $MAVEN_DEBUG_OPTS $EXTRA_TEST_OPTS"

    # check if the first parameter is a branch name - if yes, checkout that branch instead of copying the working dir
    if [ -n "$1" ] && (git rev-parse --abbrev-ref --verify -q "$1") ; then
      BRANCH=$1
      EXPLICIT_BRANCH=yes
      shift
    else
      BRANCH=`git symbolic-ref --short HEAD`
    fi
    echo $BRANCH > $LOGS_DIR/branch

    PROJECT=`basename \`pwd\``
    echo Running off branch $BRANCH
    UPSTREAM_BRANCH=`find_upstream_branch $BRANCH`
#    DEST=/tmp/privatebuild/$PROJECT/$UPSTREAM_BRANCH
#    DEST=/tmp/privatebuild/$PROJECT
    DEST=../privatebuild/$PROJECT

    if [ -z "$UPSTREAM_BRANCH" ] ; then
      return 1
    fi

    if [ -n "$EXPLICIT_BRANCH" ] ; then
      if [ $CLEAN_BUILD -eq 1 ] ; then
        print_and_run rm -r $DEST
        print_and_run git clone -slb "$BRANCH" . $DEST
      else
        echo Cannot test a custom branch without building and cleaning the directory >&2
        return 2
      fi
    else
      print_and_run mkdir -p $DEST
      print_and_run rsync -av --delete --link-dest=. --exclude '.git' --exclude 'target' --exclude '*.log' . $DEST
    fi

    print_and_run cd $DEST

    # try to parse as many arguments as possible as module names
    MODULE_ARGS="" ; 
    while [ -d "$1" ] ; do
      if [ -z "$MODULE_ARGS" ] ; then
        MODULE_ARGS="-pl $1"
      else
        MODULE_ARGS="$MODULE_ARGS,$1"
      fi
      shift
    done

    echo Building modules $MODULE_ARGS
    EXTRA_ARGS="$*"

    ERRCODE=0
    if [ $CLEAN_BUILD -eq 1 ] ; then
      #CLEAN=clean
      #print_and_run mvn -nsu clean -am ${=MODULE_ARGS}
      print_and_run mvn -nsu clean
    fi


    #if [ -n "$MODULE_ARGS" ] ; then
      if [ $BUILD -eq 1 ] ; then
        #print_and_run mvn -nsu -P-extras $CLEAN install -DskipTests -am ${=MODULE_ARGS} ${=EXTRA_ARGS}
        print_and_run mvn -nsu install -DskipTests -am ${=MODULE_ARGS} ${=EXTRA_ARGS}
        ERRCODE=$?
      fi
      if [ $ERRCODE -ne 0 ] ; then
        return $ERRCODE
      fi

      if [ $TEST -eq 1 ] ; then
        print MAVEN_FORK_OPTS=$MAVEN_FORK_OPTS
        print_and_run mvn -e -o verify -Ptest-CI ${=MODULE_ARGS} $MAVEN_LOG_OPTS ${=EXTRA_ARGS}
        ERRCODE=$?
        return $ERRCODE
      fi
}

print JAVA_HOME=$JAVA_HOME

case `basename $0` in
  cbuild) 	big_build_function 1 1 0 $* ;;
  jbuild) 	big_build_function 0 1 0 $* ;;
  jtest) 	big_build_function 0 0 1 $* ;;
  btest) 	big_build_function 0 1 1 $* ;;
  cbtest) 	big_build_function 1 1 1 $* ;;
  *) 	echo Unrecognized executable name: $0 >&2 ; exit 1
esac

