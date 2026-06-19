TS_PACKAGES = core/pi pi-ui workspace/pi pi-tasks pi-git pi-engineering pi-companion/pi pi-swarm/extension

sync:
	uv sync --extra companion

compile:
	uv lock -U
	make sync

test:
	uv run pytest basecamp-cli/tests pi-companion/tui/tests
	@for pkg in $(TS_PACKAGES); do \
		echo "--- $$pkg ---"; \
		npm --prefix $$pkg test 2>&1 | tail -3; \
	done

lint:
	uv run ruff check . && uv run ruff format --check .
	@for pkg in $(TS_PACKAGES); do \
		echo "--- $$pkg ---"; \
		npm --prefix $$pkg run check 2>&1 | tail -3; \
	done

fix:
	uv run ruff check --fix . && uv run ruff format .
	@for pkg in $(TS_PACKAGES); do \
		echo "--- $$pkg ---"; \
		npm --prefix $$pkg run lint:fix 2>&1 | tail -1; \
		npm --prefix $$pkg run format 2>&1 | tail -1; \
	done
