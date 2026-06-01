sync:
	uv sync

compile:
	uv lock -U
	make sync

test:
	uv run pytest
	npm --prefix pi-extension test

lint:
	uv run ruff check . && uv run ruff format --check .
	npm --prefix pi-extension run check

fix:
	uv run ruff check --fix . && uv run ruff format .
	npm --prefix pi-extension run lint:fix && npm --prefix pi-extension run format
