#!/bin/bash
set -e

if [ -z "${BRIDGE_DB_URL}" ]; then
    echo "BRIDGE_DB_URL is unset or set to the empty string"
    exit 1
fi

# Run migrations
source .venv/bin/activate

alembic -n local_docker upgrade head

cd /srv/bridge_backend/certs/ && ./create_node_certs.sh

python -m bridge
