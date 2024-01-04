export PYENV_ROOT := $(HOME)/.pyenv
export PATH := $(PYENV_ROOT)/bin:$(PATH)

.PHONY: init
init:
	pip install poetry==1.7.1
	# Could add to pyproject toml but we want to run pre-commit hooks
	# to also other than python files
	pip install pre-commit

.PHONY: deps
deps:
	cd bridge_node && poetry config virtualenvs.in-project true && poetry install

.PHONY: serve
serve:
	docker-compose -f docker-compose.dev.yaml up -d --build

.PHONY: lint
lint:
	cd bridge_node && poetry run ruff check
	cd bridge_node && poetry run ruff format --check

.PHONY: test
test:
	cd bridge_node && poetry run pytest

.PHONY: coverage
coverage:
	cd bridge_node && poetry run coverage run && poetry run coverage report

.PHONY:format
format:
	cd bridge_node && poetry run ruff format

.PHONY: migrate
migrate:
	cd bridge_node && poetry run alembic -n dev_from_outside upgrade head

.PHONY: install
install:
	cd bridge_node && poetry install && poetry build
