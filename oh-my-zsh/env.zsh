# java-related stuff
#export OPEN_JDK7_HOME=/lib/jvm/java-1.7.0-openjdk
export OPEN_JDK8_HOME=$HOME/Tools/openjdk8
#export ORACLEJAVA6_HOME=/usr/java/jdk1.6.0_45
export ORACLE_JDK7_HOME=$HOME/Tools/java7
export ORACLE_JDK8_HOME=$HOME/Tools/java8
export JAVA_HOME=$ORACLE_JDK8_HOME
export M2_HOME=/usr/share/maven

# for jdk7 disassembly
#export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:$HOME/Tools/hsdis

# path
export PATH=$PATH:$HOME/bin

# maven
export MAVEN_OPTS="-ea -server -XX:+AggressiveOpts -XX:+UseCompressedOops -XX:+UseG1GC"
export MAVEN_FORK_OPTS="-ea -server -XX:+AggressiveOpts -XX:+UseCompressedOops -XX:+UseG1GC -Xmx1024m"

# github
export GITHUB_OAUTH_TOKEN="e2dcaf57a9e37c2cd2e7de4af6ee38492cf5aa49"

# extra zsh autocompletion options
export FPATH=$FPATH:~/bin/zsh

# editor
export EDITOR=vim
