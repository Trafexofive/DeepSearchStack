#!/bin/sh
# wait-for-it.sh: A script to wait for a service to be available before executing a command.

set -e

host="$1"
shift
cmd="$@"

# Default timeout is 15 seconds
TIMEOUT=15

echo "Waiting for $host..."

for i in `seq $TIMEOUT` ; do
  nc -z "$host" 80 && echo "Service $host is ready." && exec $cmd
  sleep 1
done

echo "Timed out waiting for $host"
exit 1
