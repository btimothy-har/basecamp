"""Harbor adapter for the Basecamp subagent-enabled evaluation profile."""

from __future__ import annotations

from typing import Any, ClassVar, Final, override

from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from .basecamp_pi import _CONTAINER_SOURCE, BasecampPiSingle

_PROFILE: Final = "basecamp-pi-swarm"
_SWARM_LOGS: Final = "/logs/agent/swarm"
_LARGE_FILE_SIZE: Final = "+50M"

# Initialise the task workdir as a git repository so the production deliverable
# posture applies unchanged: dispatched agents branch from clean HEAD in their own
# transient worktrees and integrate by merge. Pre-existing task repositories (the
# git-centric tasks) are left completely untouched. Files over the size cap go into
# .git/info/exclude — never into the object store or worktree checkouts — keeping
# data-heavy tasks from paying a per-dispatch re-materialisation cost; agents can
# still read them at the task-dir path. Idempotent: a resume finds the repository
# and keeps the first run's report.
_GIT_INIT_COMMAND: Final = (
    "set -euo pipefail; "
    f"mkdir -p {_SWARM_LOGS}; "
    "if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then "
    f"[ -f {_SWARM_LOGS}/git-init.json ] || "
    'printf \'{"initialized": false, "reason": "existing repository", "excluded_count": 0}\\n\' '
    f"> {_SWARM_LOGS}/git-init.json; "
    "exit 0; "
    "fi; "
    'git config --global user.name >/dev/null 2>&1 || git config --global user.name "basecamp-eval"; '
    'git config --global user.email >/dev/null 2>&1 || git config --global user.email "basecamp-eval@localhost"; '
    "git init --initial-branch=main --quiet; "
    f"find . -path ./.git -prune -o -type f -size {_LARGE_FILE_SIZE} -print "
    f"| sed -e 's|^\\./|/|' > {_SWARM_LOGS}/git-init-excluded.txt; "
    f"cat {_SWARM_LOGS}/git-init-excluded.txt >> .git/info/exclude; "
    "git add -A; "
    'git commit --quiet --allow-empty -m "Task initial state"; '
    f'excluded=$(wc -l < {_SWARM_LOGS}/git-init-excluded.txt | tr -d " "); '
    'printf \'{"initialized": true, "excluded_count": %s}\\n\' "$excluded" '
    f"> {_SWARM_LOGS}/git-init.json"
)

# Best-effort evidence harvest: child session transcripts, run sidecars, and the
# daemon store are the only record of what the dispatch surface did in a trial,
# and they live under $HOME, which harbor does not preserve. Never fails the run.
_HARVEST_COMMAND: Final = (
    f"mkdir -p {_SWARM_LOGS}; "
    f"rm -rf {_SWARM_LOGS}/agents; "
    f'cp -r "$HOME/.pi/basecamp/swarm/agents" {_SWARM_LOGS}/agents 2>/dev/null || true; '
    "for f in daemon.db daemon.db-wal daemon.db-shm; do "
    f'cp "$HOME/.pi/basecamp/swarm/$f" "{_SWARM_LOGS}/$f" 2>/dev/null || true; '
    "done; true"
)


class BasecampPiSwarm(BasecampPiSingle):
    """Pi with Basecamp's daemon-backed dispatch surface enabled in-container.

    Differences from ``basecamp-pi-single``: the session is top-level (no
    ``BASECAMP_AGENT_DEPTH``), the Python distribution ships in the archive and the
    hub daemon is installed and preflighted, and the task workdir is git-initialised
    so dispatched agents get the production worktree/branch/merge posture. Children
    ride the trial model (persona aliases degrade to inherit without config.json)
    and inherit the sandbox trio via basecamp's launch-flag-rooted propagation.
    """

    ARCHIVE_MEMBERS: ClassVar[tuple[str, ...]] = (
        *BasecampPiSingle.ARCHIVE_MEMBERS,
        "pyproject.toml",
        "src",
        "uv.lock",
    )
    APT_PACKAGES: ClassVar[tuple[str, ...]] = (*BasecampPiSingle.APT_PACKAGES, "git", "procps")
    # Depth 0 presents the session as top-level so the dispatch surface registers
    # (pinned explicitly so a caller-supplied depth cannot demote the session to a
    # no-dispatch worker). MAX_DEPTH=1 caps the tree at one level — the daemon reads
    # it from its own environment, inherited from the preflight exec.
    PROFILE_ENV: ClassVar[dict[str, str]] = {
        "BASECAMP_AGENT_DEPTH": "0",
        "BASECAMP_AGENT_MAX_DEPTH": "1",
        "BASECAMP_EXTERNAL_SANDBOX": "1",
        "BASECAMP_BASH_REVIEWER": "off",
    }

    @staticmethod
    @override
    def name() -> str:
        return _PROFILE

    @override
    async def _install_profile_extras(self, environment: BaseEnvironment) -> None:
        await self._install_daemon(environment)
        await self._preflight_daemon(environment)

    async def _install_daemon(self, environment: BaseEnvironment) -> None:
        # Pinned resolve from the committed lock keeps the profile's pin-everything
        # posture for the daemon's Python dependencies.
        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; "
                "curl -LsSf https://astral.sh/uv/install.sh | sh && "
                f'cd "{_CONTAINER_SOURCE}" && '
                '"$HOME/.local/bin/uv" sync --frozen --no-dev && '
                ".venv/bin/basecamp --help >/dev/null"
            ),
        )
        # The session spawns the daemon by bare name; /usr/local/bin is on every default
        # PATH, and $HOME resolves to the agent user at spawn time.
        await self.exec_as_root(
            environment,
            command=(
                'printf \'#!/bin/sh\\nexec "$HOME/.basecamp-eval/source/.venv/bin/basecamp" "$@"\\n\' '
                "> /usr/local/bin/basecamp && chmod 755 /usr/local/bin/basecamp"
            ),
        )

    async def _preflight_daemon(self, environment: BaseEnvironment) -> None:
        # Start the hub against its real socket path and require a health response:
        # a broken daemon fails the install loudly instead of silently degrading every
        # trial to the no-dispatch surface. The daemon is left running — session-start
        # ensure pings first and reuses it, removing the cold-start window.
        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; "
                'runtime="$HOME/.pi/basecamp/swarm"; '
                'mkdir -p "$runtime" && chmod 700 "$runtime"; '
                'setsid /usr/local/bin/basecamp hub --uds "$runtime/daemon.sock" '
                '--pidfile "$runtime/daemon.pid" --db "$runtime/daemon.db" '
                "</dev/null >/dev/null 2>&1 & "
                "for _ in $(seq 1 50); do "
                '{ [ -S "$runtime/daemon.sock" ] && '
                'curl -sf --unix-socket "$runtime/daemon.sock" http://basecamp/health >/dev/null && '
                "exit 0; } || true; "
                "sleep 0.2; "
                "done; "
                'echo "basecamp hub preflight failed" >&2; exit 1'
            ),
        )

    @override
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        # Not decorated with @with_prompt_template: super().run() applies the prompt
        # template, so decorating here would render the instruction twice.
        await self.exec_as_agent(environment, command=_GIT_INIT_COMMAND)
        try:
            await super().run(instruction, environment, context)
        finally:
            await self.exec_as_agent(environment, command=_HARVEST_COMMAND)

    @override
    def _build_metadata(self, digest: str, runtime: dict[str, str]) -> dict[str, Any]:
        metadata = super()._build_metadata(digest, runtime)
        metadata.update(
            {
                "subagents_enabled": True,
                "agent_max_depth": 1,
                # Metadata is uploaded after _install_profile_extras: a failed preflight
                # aborts the install before this record exists.
                "daemon_preflight": "passed",
                "task_dir_git_init": "on-demand",
                "task_dir_git_init_size_cap": _LARGE_FILE_SIZE,
            }
        )
        return metadata
