#!/usr/bin/bash

#set -x
set -euo pipefail

CON=nordlayer-los-angeles-2FkI2k4LE704_udp

cp ~/.ssh/config ~/.ssh/config.old
perl -ne 'if (/^Host (.*)/) { $NAME=$1; }; if (/^(.*HostName) (.*) # (i-.*)$/) {$PREFIX=$1; $IP=$2; $ID=$3; $NEW_IP=`aws ec2 describe-instances --instance-ids $ID --query "Reservations[*].Instances[*].PublicIpAddress" --output text`; chomp($NEW_IP); if ($NEW_IP =~ /^ *$/) {$NEW_IP = "0.1.1.1";} else { print STDERR "Found $NEW_IP for $ID $NAME\n";}; print "$PREFIX $NEW_IP # $ID\n";} else {print $_;}' ~/.ssh/config > ~/.ssh/config.new
cp ~/.ssh/config.new ~/.ssh/config
diff -B1 ~/.ssh/config.old ~/.ssh/config

nmcli con down $CON && nmcli con up $CON
