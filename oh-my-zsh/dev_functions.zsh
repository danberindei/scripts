function openjdk8 {
  JAVA_HOME=$OPEN_JDK8_HOME
  echo JAVA_HOME=$(readlink $JAVA_HOME)
}

function openjdk7 {
  JAVA_HOME=$OPEN_JDK7_HOME
  echo JAVA_HOME=$(readlink $JAVA_HOME)
}

function java6 {
  JAVA_HOME=$ORACLE_JDK6_HOME
  echo JAVA_HOME=$(readlink $JAVA_HOME)
}

function java7 {
  JAVA_HOME=$ORACLE_JDK7_HOME
  echo JAVA_HOME=$(readlink $JAVA_HOME)
}

function java8 {
  JAVA_HOME=$ORACLE_JDK8_HOME
  echo JAVA_HOME=$(readlink $JAVA_HOME)
}

function java9 {
  JAVA_HOME=$ORACLE_JDK9_HOME
  echo JAVA_HOME=$(readlink $JAVA_HOME)
}
