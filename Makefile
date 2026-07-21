.PHONY: sync compile test lint fix eval eval-dry eval-install

EVAL_SELECTION ?= podman-arm64
EVAL_ENGINE ?= podman
EVAL_ATTEMPTS ?= 1
EVAL_CONCURRENCY ?= 1
EVAL_MODEL ?= openai/gpt-5.6-sol
EVAL_THINKING ?= xhigh
EVAL_PI_VERSION ?= 0.80.7
EVAL_JOBS_DIR ?= $(HOME)/evals/basecamp-terminal-bench/jobs
EVAL_EXTRA ?=

EVAL_COMMAND = uv run python -m evals.terminal_bench.run $(EVAL_SELECTION) \
	--engine $(EVAL_ENGINE) \
	--attempts $(EVAL_ATTEMPTS) \
	--concurrency $(EVAL_CONCURRENCY) \
	--model $(EVAL_MODEL) \
	--thinking $(EVAL_THINKING) \
	--pi-version $(EVAL_PI_VERSION) \
	--jobs-dir "$(EVAL_JOBS_DIR)" \
	$(EVAL_EXTRA)

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

eval:
	$(EVAL_COMMAND) --yes

eval-dry:
	$(EVAL_COMMAND) --dry-run

eval-install:
	$(EVAL_COMMAND) --install-only
