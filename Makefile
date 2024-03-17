export PYENV_ROOT := $(HOME)/.pyenv
export PATH := $(PYENV_ROOT)/bin:$(PATH)

.PHONY: init
init: install-poetry install
	pre-commit install

.PHONY: install
install:
	cd bridge_node && poetry config virtualenvs.in-project true && poetry install

.PHONY: install-poetry
install-poetry:
	@which poetry > /dev/null && echo "Using poetry at $$(which poetry)" || (echo "Poetry not found, installing" && pip install poetry==1.7.1)

.PHONY: serve
serve:
	docker compose -f docker-compose.dev.yaml up -d --build

.PHONY: lint
lint:
	cd bridge_node && poetry run ruff check
	cd bridge_node && poetry run ruff format --check

.PHONY: test
test:
	cd bridge_node && poetry run python -m pytest -s --no-cov --log-cli-level=info -v

.PHONY: test-cov
test-cov:
	cd bridge_node && poetry run python -m pytest -s --cov --log-cli-level=info -v

.PHONY: unit-test
unit-test:
	cd bridge_node && poetry run python -m pytest -m "not integration" --no-cov --log-cli-level=info -s

.PHONY: integration-test
integration-test:
	cd bridge_node && poetry run python -m pytest -m "integration" --no-cov --log-cli-level=info

.PHONY: coverage
coverage:
	cd bridge_node && poetry run coverage run

.PHONY:format
format:
	cd bridge_node && poetry run ruff format

.PHONY: migrate
migrate:
	cd bridge_node && poetry run alembic -n dev_from_outside upgrade head

.PHONY: build-python
build-python:
	cd bridge_node && poetry install && poetry build
