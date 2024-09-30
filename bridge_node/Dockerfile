FROM python:3.11-slim-bookworm AS base

WORKDIR /srv/bridge_backend

# Set environment variables.
# write bytecode to /tmp
ENV PYTHONPYCACHEPREFIX=/tmp/pycache \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.7.1

RUN apt-get update -y && apt-get --no-install-recommends -y install \
    postgresql-client \
    libsecp256k1-dev \
    && rm -rf /var/lib/apt/lists/*

FROM base AS builder

RUN apt-get update -y && apt-get --no-install-recommends -y install \
    libpq-dev \
    python3-dev \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install "poetry==$POETRY_VERSION"

COPY pyproject.toml poetry.lock ./

# Install only dependencies needed for production
RUN poetry config virtualenvs.in-project true && \
    poetry install --only=main --no-root

COPY . .

RUN poetry build && ./.venv/bin/pip install dist/*.whl

# Discard build stage and only copy the packages to the final image
FROM base AS final

COPY --from=builder /srv/bridge_backend/.venv ./.venv
COPY --from=builder /srv/bridge_backend/dist .
COPY --from=builder /srv/bridge_backend/migrations ./migrations
COPY --from=builder /srv/bridge_backend/bridge/api/monitor/templates ./templates
COPY entrypoint.sh ./
COPY alembic.ini ./

COPY scripts /srv/bridge_backend/certs/
RUN cd /srv/bridge_backend/certs/ && ./create_ca_cert.py

# Run entrypoint.sh
ENTRYPOINT ["/srv/bridge_backend/entrypoint.sh"]
