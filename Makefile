TS_PACKAGES = core/pi pi-ui workspace/pi pi-tasks pi-git pi-bash-reviewer pi-engineering pi-browser pi-companion/pi pi-swarm/extension

sync:
	uv sync --extra companion

compile:
	uv lock -U
	make sync

test:
	uv run pytest core/config/tests workspace/projects/tests pi-swarm/cli/tests pi-companion/tui/tests
	@set -e; for pkg in $(TS_PACKAGES); do \
		echo "--- $$pkg ---"; \
		npm --prefix $$pkg test; \
	done

lint:
	uv run ruff check . && uv run ruff format --check .
	@set -e; for pkg in $(TS_PACKAGES); do \
		echo "--- $$pkg ---"; \
		npm --prefix $$pkg run check; \
	done

fix:
	uv run ruff check --fix . && uv run ruff format .
	@set -e; for pkg in $(TS_PACKAGES); do \
		echo "--- $$pkg ---"; \
		npm --prefix $$pkg run lint:fix; \
		npm --prefix $$pkg run format; \
	done
