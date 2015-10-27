#!/usr/bin/python

from __future__ import print_function

import argparse
from datetime import datetime
import fileinput
import re
import sys

startTimes = {}
# 2012-01-05 10:28:16,070 TRACE (CacheStartThread,Infinispan-Cluster,___defaultcache) [org.infinispan.remoting.transport.jgroups.CommandAwareRpcDispatcher] Replication task sending CacheViewControlCommand
#startFilter = re.compile('(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) .* (\(.*\)) .*Replication task sending')
startFilter = re.compile('(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) .* (\(.*\)) .*Replication task sending TxCompletionNotificationCommand')
# 2012-01-05 10:28:16,071 TRACE (CacheStartThread,Infinispan-Cluster,___defaultcache) [org.jgroups.protocols.TCP] sending msg to TransactionsSpanningReplicatedCachesTest-NodeA-31550, src=TransactionsSpanningReplicatedCachesTest-NodeB-26062
#endFilter = re.compile('(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) .* (\(.*\)) .*sending msg')
#endFilter = re.compile('(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) .* (\(.*\)) .*sending request')
#endFilter = re.compile('(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) .* (\(.*\)) .*Sending message with future')

# 2012-01-05 15:51:47,547 TRACE [org.infinispan.remoting.transport.jgroups.JGroupsTransport] (OOB-83,erm-cluster-0a1e0c51,data-grid-4-5038) dests=[data-grid-5-27137], command=ClusteredGetCommand{key=EdgeResourceCacheKey[edgeDeviceId=18,resourceId=3811], flags=null}, mode=WAIT_FOR_VALID_RESPONSE, timeout=15000
# 2012-01-05 15:48:02,938 TRACE [org.infinispan.remoting.transport.jgroups.CommandAwareRpcDispatcher] (CacheStartThread,billing-cluster-0a1e0c51,billing) Responses: [sender=data-grid-1-23928, retval=SuccessfulResponse{responseValue=null} , received=true, suspected=false]
#startFilter = re.compile('(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) .* (\(.*\)) .*Replication task sending.*ClusteredGetCommand')
endFilter = re.compile('(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) .* (\(.*\)) .*Responses:')
#startFilter = re.compile('(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) .* (\(.*\)) .*Read version 510')
#endFilter = re.compile('(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) .* (\(.*\)) .*Stop unmarshaller')


# 2012-01-05 10:28:16,071
dateFormat = "%Y-%m-%d %H:%M:%S,%f"

def handleMessage(message):
   m = startFilter.match(message)
   if m:
      time = datetime.strptime(m.group(1) + "000", dateFormat)
      thread = m.group(2)
      #print(thread + " " + str(time) + " --> ")
      startTimes[thread] = (time, message)
   else:
      m = endFilter.match(message)
      if m:
         time = datetime.strptime(m.group(1) + "000", dateFormat)
         thread = m.group(2)
         (startTime, startMessage) = startTimes.get(thread, (None, None))
         if startTime:
            del startTimes[thread]
            duration = time - startTime
            if duration.total_seconds() > 10:
               print(str((time - startTime).total_seconds()) + " : " + startMessage +
                     "        " + message)

def main():         
   f = fileinput.input(sys.argv[1:])

   for line in f:
      handleMessage(line)

main()

