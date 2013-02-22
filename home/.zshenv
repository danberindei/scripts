# java-related stuff
export JAVA_HOME=/usr/lib/jvm/java-1.7.0-openjdk.x86_64
export JRUBY_HOME=/home/dan/tools/jruby-1.6.4
export M2_HOME=/usr/share/maven
# for jdk7 disassembly
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/home/dan/tools/hsdis

# path
export PATH=$PATH:$JAVA_HOME/bin:$JRUBY_HOME/bin:$HOME/bin

# maven
export MAVEN_OPTS="-ea -server -XX:+AggressiveOpts -XX:+UseCompressedOops -XX:+UseConcMarkSweepGC -XX:+UseParNewGC -XX:NewRatio=4"

# extra zsh autocompletion options
export FPATH=$FPATH:~/bin/zsh
