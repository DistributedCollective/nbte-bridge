Sovryn NBTE Bridge
==================

Install for development (requires python3.11 and poetry)
```
sudo apt-get install libpq-dev
pip install pre-commit
make init
```

Run unit and integration tests (requires docker and docker compose)
```
# Only needs to be run once
echo POSTGRES_PASSWORD=myrandompassword > .env

# Run all tests
make test
```
