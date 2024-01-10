# java-related stuff
export SYSTEM_OPENJDK_HOME=/usr/lib/jvm/java-openjdk
export IBMJDK8_HOME=$HOME/Tools/ibmjdk8
export OPENJDK8_HOME=$HOME/Tools/java8
export OPENJDK11_HOME=$HOME/Tools/java11
export JAVA_HOME=$OPENJDK11_HOME
#Unused by maven 3.5
#export M2_HOME=$HOME/Tools/maven

# for jdk disassembly
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:$HOME/Tools/java-disassembler

# malloc
#export LD_PRELOAD=/lib64/libjemalloc.so

# openshift
export OC_HOME=$HOME/Tools/openshift-origin-client-tools-v3.11.0-0cbc58b-linux-64bit

# path
#export PATH=$M2_HOME/bin:$HOME/bin:$PATH
export PATH=$PATH:$HOME/bin:$HOME/.local/bin:$OC_HOME

# maven
export MAVEN_OPTS="-ea -Xmx1G"
export DEBUG5005="-agentlib:jdwp=transport=dt_socket,server=n,suspend=y,address=5005"


# extra zsh autocompletion options
export FPATH=$FPATH:~/bin/zsh

# editor
export EDITOR=vim

# natural scrolling
#synclient VertScrollDelta=-115
#synclient PalmDetect=1 PalmMinWidth=10 PalmMinZ=50

