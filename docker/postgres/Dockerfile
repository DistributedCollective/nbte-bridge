# Need to use a custom docker image to install python and plpython3u inside it.
FROM postgres:16

RUN apt-get update && apt-get -y install \
    python3.11 \
    postgresql-plpython3-16 && \
    rm -rf /var/lib/apt/lists/*

COPY initsql/* /docker-entrypoint-initdb.d/
