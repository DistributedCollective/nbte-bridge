#!/bin/bash

sleep 5
echo "Waiting for PostgreSQL startup"
until psql postgresql://bridge:a5f83ab52f2c6c8d0a31e99c@postgres:5432/bridge -c "SELECT 1" ; do
  sleep 5
done
echo "PostgreSQL started"

# Run migrations
source .venv/bin/activate

alembic -n local_docker upgrade head

python -m bridge
