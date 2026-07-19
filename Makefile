# Bare `make` sets up the dev venv — never the global bootstrap (`make install`),
# which mutates ~/.claude and ~/.pi/basecamp/config.json.
.DEFAULT_GOAL := sync

install:
	uv run install.py

sync:
	uv sync --all-extras

compile:
	uv lock -U
	make sync

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check .

fix:
	uv run ruff check --fix . && uv run ruff format .
