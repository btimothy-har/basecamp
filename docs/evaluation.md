# Evaluation

Basecamp includes a repository-local [Harbor](https://harborframework.com) adapter for running Pi with Basecamp on Terminal-Bench 2.1. Harbor runs on the host and creates a fresh, disposable Docker container for every task attempt; Pi and Basecamp execute only inside that trial container.

Prerequisites:

- Python 3.12+ and `uv`
- Docker, or a running Podman machine
- A dedicated, scoped model-provider API key
- A committed Basecamp revision; uncommitted and untracked files are deliberately excluded

Install the pinned harness stack:

```bash
uv tool install --force --prerelease explicit \
  --with 'litellm==1.90.2' \
  'harbor==0.20.1.dev202607210139'
```

For Podman on macOS, the launcher puts Basecamp's compatibility wrapper on `PATH` automatically. It uses `DOCKER_COMPOSE_BIN` or an installed `docker-compose` when available; otherwise it downloads Docker Compose v5.3.1 into `~/.cache/basecamp/evals/`, verifies the pinned SHA-256, and points it at the running Podman machine's API socket. `podman-compose` is not compatible with Harbor because it does not accept Compose's `--project-directory` option.

From the Basecamp repository root, export the scoped provider credentials referenced by your Pi configuration, then use the Make targets:

```bash
export OPENAI_API_KEY='<scoped-key>'
export PI_PROXY_API_KEY='<scoped-proxy-key>'

make eval-dry       # print the resolved tasks and Harbor command
make eval-install   # install/config/auth smoke without model completions
make eval           # run the selected tasks (paid model calls)
```

The default `podman-arm64` preset runs the three native-arm64 tasks whose 2 GiB limits fit the local Podman machine:

- `terminal-bench/hf-model-inference`
- `terminal-bench/mteb-retrieve`
- `terminal-bench/pytorch-model-recovery`

Useful overrides:

```bash
# Include the fourth native-arm64 task (8 GiB limit)
make eval EVAL_SELECTION=podman-arm64-all

# The amd64 preset used by the GitHub Actions workflow (34 tasks, Docker only)
make eval EVAL_SELECTION=docker-amd64 EVAL_ENGINE=docker

# The full terminal-bench-2-1 dataset (cannot be combined with other selections)
make eval EVAL_SELECTION=all EVAL_ENGINE=docker

# Choose arbitrary tasks
make eval EVAL_SELECTION="hf-model-inference pytorch-model-recovery"

# Repeat tasks and control parallelism
make eval EVAL_ATTEMPTS=3 EVAL_CONCURRENCY=2

# Change model/runtime settings
make eval EVAL_MODEL=shopify/fireworks:accounts/fireworks/models/glm-5p2 \
  EVAL_THINKING=high EVAL_PI_VERSION=0.83.0

# Use Docker, omit models.json, or change the result root
make eval EVAL_ENGINE=docker EVAL_EXTRA=--no-models \
  EVAL_JOBS_DIR="$HOME/evals/other-terminal-bench-jobs"
```

`make eval` is the explicit paid-run action. `make eval-dry` permits a dirty worktree because it does not launch Harbor; executable runs require a clean worktree so the printed Git commit identifies the exact Basecamp source. Change the provider key and `EVAL_MODEL` together when using another provider. Harbor passes provider credentials into each trial container; do not use a broad personal or organization key. `make eval-install` requires `pi --list-models` to contain the exact configured provider/model before Harbor removes each trial container.

`pi_models_file` is optional. When present, the adapter snapshots and digest-verifies that `models.json`, copies it to the trial user's Pi config with mode `0600`, and forwards host environment variables referenced by provider `apiKey` or header interpolation. Literal API keys and credential commands are rejected. `auth.json`, `settings.json`, and secret values are never copied into metadata or the Basecamp source archive.

The adapter installs the exact Pi version and a `git archive` of `package.json`, `package-lock.json`, and `pi/` from the clean `HEAD` commit resolved by the launcher. It verifies the archive digest, installs production dependencies from the committed lockfile without lifecycle scripts, and registers Basecamp with Pi. It never mounts host Pi auth, Basecamp configuration, worktrees, or the repository into the trial container.

This is the worker-like `basecamp-pi-single` profile. It retains Basecamp's system prompt, skills, task workflow, project/workspace behavior, engineering tools, and structured file tools. It disables the Python hub, dispatched subagents, browser, workstreams, code-review UI, and interactive `plan()` flow.

One model-backed feature is **not** exercised: the **bash reviewer** is explicitly disabled (`BASECAMP_BASH_REVIEWER=off`, honoured only alongside the sandbox env signal and the `--unsafe-edit-sandboxed` launch flag). It resolves its judge from basecamp's `fast` alias, which the trial container — never receiving basecamp's `config.json` — cannot provide. Left on, it could not reach a model, and its no-UI failsafe is fail-closed — so every gated command would be hard-blocked rather than judged, scoring a missing alias instead of the agent.

The **continuation guard** is active in trials: its judge rides the active session model, which the installed `models.json` provides, so it judges each stop and nudges premature ones. Its posture is fail-open — any model-resolution or judge failure simply means no nudge.

Both states are recorded per trial in `agent/basecamp-eval.json` (`bash_reviewer_enabled: false`, `continuation_guard_active: true`) so a score is never misread. Scores from this profile therefore measure the prompt, tools, workflow, and stop judgement — not basecamp's command gating. The adapter marks the trial with `BASECAMP_EXTERNAL_SANDBOX=1` and supplies both `--unsafe-edit` and `--unsafe-edit-sandboxed`; Basecamp requires all three signals before allowing `edit`/`write` in a headless subagent session. Read-only and ordinary headless or subagent sessions remain protected.

Harbor writes each job and trial beneath `EVAL_JOBS_DIR` (default: `~/evals/basecamp-terminal-bench/jobs`). The useful per-trial files are:

- `result.json` — reward, timing, and exception data
- `agent/pi.txt` — Pi's filtered JSON event stream
- `agent/pi/sessions/` — Pi session data
- `agent/basecamp-eval.json` — Basecamp commit, archive digest, profile, and runtime versions
- `verifier/` — reward and verifier output

Browse completed jobs with:

```bash
harbor view "$HOME/evals/basecamp-terminal-bench/jobs"
```

Docker and Podman-on-macOS through the included wrapper are supported. Most Terminal-Bench 2.1 task images are amd64-only and x64 Node can crash under arm64 emulation, so the Podman presets select the four images that publish native arm64 variants, while `docker-amd64` and `all` assume an amd64 Docker host. Runs produce local scores and Pi logs, not ATIF trajectories, so they are not eligible for the Terminal-Bench 2.1 leaderboard. Harbor's usage totals cover the parent Pi process; the continuation guard's judge calls are auxiliary completions, so usage totals may not account for them.

The launcher reconciles each finished run: when Harbor silently drops a task filter that matches nothing (dataset drift), the trial count no longer equals tasks x attempts and the launch fails with an explicit error instead of reporting a silently smaller result.

## GitHub Actions

`.github/workflows/terminal-bench.yml` runs the same launcher on GitHub-hosted runners, routing model traffic directly through OpenRouter. It triggers manually (`workflow_dispatch`); a weekly Monday 06:00 UTC cron is prepared but intentionally disabled until dispatched runs prove the pipeline (restore note in the workflow). Matrix legs are (model, thinking) pairs: ad hoc dispatches default to a single `openrouter/z-ai/glm-5.2` leg, while the weekly run — once re-enabled — executes every leg (`z-ai/glm-5.2`, `moonshotai/kimi-k3`, `qwen/qwen3.8-max`, `deepseek/deepseek-v4-pro`, `deepseek/deepseek-v4-flash-0731`, `openai/gpt-5.6-terra`, `openai/gpt-5.6-sol`, `anthropic/claude-opus-5`, `anthropic/claude-opus-4.8`, all via OpenRouter) at their per-model thinking defaults (xhigh), the `docker-amd64` preset, 3 attempts — nine legs across five shards, so 45 jobs. DeepSeek Flash is pinned to the dated `0731` snapshot rather than the rolling alias so a score names the exact weights it measured; OpenRouter publishes no dated snapshots for the four frontier legs, so those name rolling aliases and a score cannot pin their weights the same way. Dispatch inputs cover the model(s), task-set, attempts, concurrency, a thinking override (or `per-model`, which uses each model's default — xhigh for Anthropic/OpenAI legs, provider-max effort for the others via their `thinkingLevelMap`), and the Pi version.

The override list includes `max`, which only the Anthropic and OpenAI legs distinguish from xhigh — the open-weight maps already send provider-max at xhigh. Those legs stay at xhigh by default because both vendors name xhigh as the setting for coding and agentic work and warn that max overthinks, and because a trial container is CPU-capped, which turns extra reasoning into wall clock spent against the agent timeout. `max` is therefore an opt-in A/B, not the default.

`thinkingLevelMap` values are the provider effort strings OpenRouter validates against, so each leg's map is checked against the live endpoint rather than assumed. `qwen/qwen3.8-max` is the one leg that rejects `none` ("reasoning is mandatory for this endpoint"); its `off` level is therefore mapped to `null`, which Pi reads as unsupported and clamps up to `minimal` instead of issuing a request that would 400. The four frontier maps are the exception: they are derived from Pi's shipped OpenRouter catalog rather than probed against the endpoint, and `xhigh`/`max` are newer effort strings than `low`/`high`, so run a `docker-smoke` dispatch per new leg to confirm OpenRouter passes them through before paying for a full run.

Each matrix leg verifies OpenRouter reachability with the configured key before any paid work, installs `evals/terminal_bench/models.ci.json` (a secret-free template whose `$OPENROUTER_API_KEY` reference is interpolated by Pi at run time), and publishes a score summary plus a curated artifact containing only job-level result and config files.

Required repository secret: `OPENROUTER_API_KEY` (an eval-scoped OpenRouter key).
