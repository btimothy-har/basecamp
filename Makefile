sync:
	uv sync --all-extras

compile:
	uv lock -U
	make sync

test:
	uv run pytest
	npm test

lint: check-namespace
	uv run ruff check . && uv run ruff format --check .
	npm run check

fix:
	uv run ruff check --fix . && uv run ruff format .
	npm run lint:fix
	npm run format

# namespace-portion guard: a stray basecamp/__init__.py silently shadows sibling portions
check-namespace:
	@stray=$$(find src core/py workspace/py swarm/py companion/py -maxdepth 2 -path "*/basecamp/__init__.py" 2>/dev/null); \
	if [ -n "$$stray" ]; then echo "namespace violation — basecamp/__init__.py must not exist:"; echo "$$stray"; exit 1; fi
