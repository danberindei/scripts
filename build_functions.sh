#!/bin/zsh

function print_and_run() {
  echo ### $*
  CMD=$1 ; shift
  $CMD ${=*}
  if [ $? -ne 0 ] ; then
    return 9
  fi
}

function big_build_function() {
    # maven options
    #MAVEN_TUNING_OPTS="-server -XX:+AggressiveOpts -XX:+UseCompressedOops -XX:+UseConcMarkSweepGC -XX:+UseParNewGC -XX:NewRatio=3"
    MAVEN_TUNING_OPTS="-server -XX:+UseCompressedOops -XX:+UseConcMarkSweepGC -XX:+UseParNewGC -XX:NewRatio=4"
    MAVEN_MEMORY_OPTS="-Xmx900m -XX:MaxPermSize=300m -Xss500k -XX:+HeapDumpOnOutOfMemoryError"
    MAVEN_JGROUPS_OPTS="-Djava.net.preferIPv4Stack=true -Djgroups.bind_addr=127.0.0.1"
    # for tests only
    #MAVEN_DEBUG_OPTS="-ea"
    #MAVEN_DEBUG_OPTS="-ea -Xdebug -Xrunjdwp:transport=dt_socket,server=y,suspend=n,address=5006"
    MAVEN_DEBUG_OPTS="-ea -agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=5006"
    MAVEN_LOG_OPTS=""
    MAVEN_LOG_OPTS="-Dlog4j.configuration=file:/home/dan/Work/infinispan/log4j-trace.xml"

    MAVEN_OPTS="$MAVEN_TUNING_OPTS $MAVEN_MEMORY_OPTS $MAVEN_JGROUPS_OPTS $EXTRA_BUILD_OPTS"

    LOGS_DIR=`pwd`/../logs

    CLEAN_BUILD=$1 ; shift
    BUILD=$1 ; shift
    TEST=$1 ; shift
    DEBUG=$1 ; shift
    #echo params: $CLEAN_BUILD $BUILD $TEST $DEBUG

    # check if the first parameter is a branch name - if yes, checkout that branch instead of copying the working dir
    if [ -n "$1" ] && (git rev-parse --abbrev-ref --verify -q "$1") ; then
      BRANCH=$1
      EXPLICIT_BRANCH=yes
      shift
    else
      BRANCH=`git symbolic-ref --short HEAD`
    fi

    PROJECT=`basename \`pwd\``
    echo Running off branch $BRANCH
    UPSTREAM_BRANCH=`find_upstream_branch $BRANCH`
    DEST=/tmp/privatebuild/$PROJECT/$UPSTREAM_BRANCH

    if [ -z "$UPSTREAM_BRANCH" ] ; then
      exit 1
    fi

    if [ -n "$EXPLICIT_BRANCH" ] ; then
      print_and_run rm -r $DEST
      print_and_run git clone -slb "$BRANCH" . $DEST
    else
      print_and_run mkdir -p $DEST
      print_and_run rsync -a --delete --link-dest=. --exclude '.git' --exclude 'target' --exclude '*.log' . $DEST
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

    if [ $CLEAN_BUILD -eq 1 ] ; then
      print_and_run mvn -nsu -P-extra clean ${=MODULE_ARGS} ${=EXTRA_ARGS}
    fi
    if [ $? -ne 0 ] ; then
      exit 9
    fi

    if [ $BUILD -eq 1 ] ; then
      print_and_run mvn -nsu -P-extra install -DskipTests -am ${=MODULE_ARGS} ${=EXTRA_ARGS}
    fi
    if [ $? -ne 0 ] ; then
      exit 9
    fi

    if [ $TEST -eq 1 ] ; then
      if [ $DEBUG -ne 1 ] ; then
        MAVEN_DEBUG_OPTS=""
      fi
      MAVEN_OPTS="$MAVEN_OPTS $MAVEN_DEBUG_OPTS $MAVEN_LOG_OPTS $EXTRA_TEST_OPTS" print_and_run mvn surefire:test ${=MODULE_ARGS} ${=EXTRA_ARGS}
      ERRCODE=$?
#      if [ $ERRCODE -ne 0 ] ; then
#        print_and_run popd
#        print_and_run ../failedTestLogs.sh $LOGS_DIR/infinispan.log
#        return 9
#      fi
    fi
}

case `basename $0` in
  cbuild) 	big_build_function 1 1 0 0 $* ;;
  jbuild) 	big_build_function 0 1 0 0 $* ;;
  jtest) 	big_build_function 0 0 1 0 $* ;;
  btest) 	big_build_function 0 1 1 0 $* ;;
  cbtest) 	big_build_function 1 1 1 0 $* ;;
  dtest)        big_build_function 0 0 1 1 $* ;;
  *) 	echo Unrecognized executable name: $0 >&2
esac

