sync:
	uv sync --all-extras

compile:
	uv lock -U
	make sync

test:
	uv run pytest
	npm test

lint:
	uv run ruff check . && uv run ruff format --check .
	npm run check

fix:
	uv run ruff check --fix . && uv run ruff format .
	npm run lint:fix
	npm run format
