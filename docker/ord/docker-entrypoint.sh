#!/bin/sh
set -e

# containers on linux share file permissions with hosts.
# assigning the same uid/gid from the host user
# ensures that the files can be read/write from both sides
if ! id ord > /dev/null 2>&1; then
  USERID=${USERID:-1000}
  GROUPID=${GROUPID:-1000}

  echo "adding user ord ($USERID:$GROUPID)"
  groupadd -f -g $GROUPID ord
  useradd -r -u $USERID -g $GROUPID ord
  chown -R $USERID:$GROUPID /home/ord
fi

if [ $(echo "$1" | cut -c1) = "-" ]; then
  echo "$0: assuming arguments for ord"

  set -- ord "$@"
fi

if [ "$1" = "ord" ] ; then
  echo "Running as ord user: $@"
  exec gosu ord "$@"
fi

echo "$@"
exec "$@"
