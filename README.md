Sovryn NBTE Bridge
==================

Install for development (requires python3.11 and poetry)
```
sudo apt-get install libpq-dev
pip install pre-commit
make init
```

Run integration tests (requires docker and docker compose)
```
cat POSTGRES_PASSWORD=myrandompassword > .env
make integration-test
```
