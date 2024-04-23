#!/bin/bash
set -e

if [ -z "${BRIDGE_DB_URL}" ]; then
    echo "BRIDGE_DB_URL is unset or set to the empty string"
    exit 1
fi

sleep 5
echo "Waiting for PostgreSQL startup at $BRIDGE_DB_URL"
until psql $BRIDGE_DB_URL -c "SELECT 1" ; do
  sleep 5
done
echo "PostgreSQL started"

# Run migrations
source .venv/bin/activate

alembic -n local_docker upgrade head

cd /srv/bridge_backend/certs/ && ./create_node_certs.py

python -m bridge
