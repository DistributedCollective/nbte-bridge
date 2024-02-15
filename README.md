Sovryn NBTE Bridge
==================

Install for development (requires python3.11 and poetry)
```
make install
```

Run integration tests (requires docker and docker-compose)
```
cat POSTGRES_PASSWORD=myrandompassword > .env
make integration-test
```