function openjdk8 {
  ln -sfT $OPEN_JDK8_HOME $JAVA_HOME
  echo JAVA_HOME=$(readlink $JAVA_HOME)
}

function openjdk7 {
  ln -sfT $OPEN_JDK7_HOME $JAVA_HOME
  echo JAVA_HOME=$(readlink $JAVA_HOME)
}

function java6 {
  ln -sfT $ORACLE_JDK8_HOME $JAVA_HOME
  echo JAVA_HOME=$(readlink $JAVA_HOME)
}

function java7 {
  ln -sfT $ORACLE_JDK7_HOME $JAVA_HOME
  echo JAVA_HOME=$(readlink $JAVA_HOME)
}

function java8 {
  ln -sfT $ORACLE_JDK8_HOME $JAVA_HOME
  echo JAVA_HOME=$(readlink $JAVA_HOME)
}
