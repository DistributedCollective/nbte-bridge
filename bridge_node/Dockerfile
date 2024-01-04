FROM python:3.11-slim-bookworm as base

WORKDIR /srv/bridge_backend

# Set environment variables.
# write bytecode to /tmp
ENV PYTHONPYCACHEPREFIX=/tmp/pycache \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.7.1

RUN apt-get update -y && apt-get --no-install-recommends -y install \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

FROM base as builder

RUN apt-get update -y && apt-get --no-install-recommends -y install \
    libpq-dev \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install "poetry==$POETRY_VERSION"

COPY pyproject.toml poetry.lock ./

# Install only dependencies needed for production
RUN poetry config virtualenvs.in-project true && \
    poetry install --only=main --no-root

COPY . .

RUN poetry build && ./.venv/bin/pip install dist/*.whl

# Discard build stage and only copy the packages to the final image
FROM base as final

COPY --from=builder /srv/bridge_backend/.venv ./.venv
COPY --from=builder /srv/bridge_backend/dist .
COPY --from=builder /srv/bridge_backend/migrations ./migrations
COPY entrypoint.sh ./
COPY alembic.ini ./

# Run entrypoint.sh
ENTRYPOINT ["/srv/bridge_backend/entrypoint.sh"]
