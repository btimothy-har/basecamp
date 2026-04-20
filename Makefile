sync:
	uv sync

compile:
	uv lock -U
	make sync

test:
	uv run pytest
	cd observer && uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check .
	cd extension && npm run check

fix:
	uv run ruff check --fix . && uv run ruff format .
	cd extension && npm run lint:fix && npm run format
