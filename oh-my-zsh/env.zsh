# java-related stuff
#export ORACLEJAVA6_HOME=/usr/java/jdk1.6.0_45
export ORACLE_JDK7_HOME=$HOME/Tools/java7
export ORACLE_JDK8_HOME=$HOME/Tools/java8
export ORACLE_JDK9_HOME=$HOME/Tools/java9
export JAVA_HOME=$ORACLE_JDK8_HOME
export M2_HOME=$HOME/Tools/maven

# for jdk disassembly
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:$HOME/Tools/java-disassembler

# path
#export PATH=$M2_HOME/bin:$HOME/bin:$PATH
export PATH=$PATH:$HOME/bin

# maven
#export MAVEN_OPTS="-ea -server -XX:+AggressiveOpts -XX:+UseCompressedOops -XX:+UseG1GC"


# github
export GITHUB_OAUTH_TOKEN="e2dcaf57a9e37c2cd2e7de4af6ee38492cf5aa49"

# extra zsh autocompletion options
export FPATH=$FPATH:~/bin/zsh

# editor
export EDITOR=vim
