"""The ``bcc`` launcher: hand off to an interactive Claude session.

Computes the ``{{ENVIRONMENT}}`` block for the committed ``system-prompt.md``,
provisions a throwaway scratch directory, exports the ``BASECAMP_*`` env the
session (and its subagents) inherit, then ``execvp``s ``claude`` — the launcher
process *becomes* the interactive session. No print mode, no chdir.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from basecamp.claude.gitutil import run_git
from basecamp.claude.identity import repo_identity, repo_root
from basecamp.claude.paths import shipped_prompts_dir

CLAUDE_COMMAND = "claude"
SCRATCH_ROOT = Path("/tmp/claude")  # noqa: S108  # deliberate shared throwaway root
_ENVIRONMENT_PLACEHOLDER = "{{ENVIRONMENT}}"
_PROMPT_FILENAME = ".bcc-system-prompt.md"


@dataclass(frozen=True)
class LaunchPlan:
    """Everything ``run_launch`` needs to write the prompt file and hand off."""

    argv: list[str]
    env: dict[str, str]
    scratch_dir: Path
    prompt: str
    prompt_path: Path


def _main_worktree(cwd: str) -> str | None:
    """Primary checkout path (first ``worktree`` entry of ``worktree list``)."""
    output = run_git(cwd, "worktree", "list", "--porcelain")
    if not output:
        return None
    for line in output.splitlines():
        if line.startswith("worktree "):
            return line.removeprefix("worktree ").strip() or None
    return None


def _render_environment(cwd: str) -> str:
    """Render the runtime environment facts substituted into the GEN prompt."""
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
    today = datetime.now(UTC).astimezone().date().isoformat()
    lines = [
        f"- User: {user}",
        f"- Platform: {sys.platform}",
        f"- Today's date: {today}",
        f"- Working directory: {cwd}",
    ]

    root = repo_root(cwd)
    if root is None:
        lines.append("- Git repository: No")
        return "\n".join(lines)

    lines.append("- Git repository: Yes")
    remote = run_git(cwd, "remote", "get-url", "origin")
    if remote:
        lines.append(f"- Git remote: {remote}")
    branch = run_git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    if branch:
        lines.append(f"- Current branch: {branch}")

    main = _main_worktree(cwd)
    if main and os.path.realpath(main) != os.path.realpath(root):
        lines.append(f"- Active worktree: {root}")
        lines.append(f"- Protected checkout: {main}")

    return "\n".join(lines)


def _scratch_dir(cwd: str, identity: str | None) -> Path:
    """``/tmp/claude/<org>/<name>`` in a repo, else ``/tmp/claude/<cwd basename>``."""
    name = identity or os.path.basename(os.path.abspath(cwd)) or "session"
    return SCRATCH_ROOT / name


def _render_prompt(cwd: str) -> str:
    """Read the committed GEN template and substitute the runtime environment."""
    template = (shipped_prompts_dir() / "system-prompt.md").read_text(encoding="utf-8")
    return template.replace(_ENVIRONMENT_PLACEHOLDER, _render_environment(cwd))


def build_launch(cwd: str, extra_args: list[str]) -> LaunchPlan:
    """Plan the launch: rendered prompt, its file path, argv, env updates, scratch dir.

    Pure (no filesystem writes) — ``run_launch`` performs the scratch mkdir and the
    prompt-file write. The prompt is handed to ``claude`` via ``--system-prompt-file``
    (full replace, identical to inline ``--system-prompt``) so the multi-KB prompt
    never rides in argv.
    """
    identity = repo_identity(cwd)
    scratch = _scratch_dir(cwd, identity)
    prompt_path = scratch / _PROMPT_FILENAME

    env = {"BASECAMP_SCRATCH_DIR": str(scratch)}
    if identity:
        env["BASECAMP_REPO"] = identity

    argv = [CLAUDE_COMMAND, "--system-prompt-file", str(prompt_path), *extra_args]
    return LaunchPlan(
        argv=argv,
        env=env,
        scratch_dir=scratch,
        prompt=_render_prompt(cwd),
        prompt_path=prompt_path,
    )


def run_launch(extra_args: list[str], cwd: str | None = None) -> None:
    """Provision scratch, write the prompt file, export env, and hand off to Claude."""
    if shutil.which(CLAUDE_COMMAND) is None:
        print(
            f"error: '{CLAUDE_COMMAND}' not found on PATH — install Claude Code first.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    plan = build_launch(cwd or os.getcwd(), extra_args)
    plan.scratch_dir.mkdir(parents=True, exist_ok=True)
    plan.prompt_path.write_text(plan.prompt, encoding="utf-8")
    os.environ.update(plan.env)
    # Clear session-identity vars a parent session may have exported so they can't
    # mis-attribute the new session in the hub. BASECAMP_REPO is set for repo
    # launches (cleared only when this launch is non-repo); the worktree vars are
    # never set here (worktree provisioning is out of scope), so always clear them.
    if "BASECAMP_REPO" not in plan.env:
        os.environ.pop("BASECAMP_REPO", None)
    os.environ.pop("BASECAMP_WORKTREE_LABEL", None)
    os.environ.pop("BASECAMP_WORKTREE_DIR", None)
    os.execvp(plan.argv[0], plan.argv)  # noqa: S606  # intentional interactive process handoff


def main() -> None:
    """Console entry point for ``bcc``."""
    run_launch(sys.argv[1:])


if __name__ == "__main__":
    main()
