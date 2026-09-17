"""Behavioral tests for Basecamp-owned OMP launch arguments."""

from __future__ import annotations

import pytest

from basecamp.core.exceptions import LauncherError
from basecamp.omp.launch_arguments import inspect_launch_arguments


def test_basecamp_flags_are_not_consumed_as_omp_values() -> None:
    detached = inspect_launch_arguments(["--model", "--detached"])
    direct = inspect_launch_arguments(["--thinking", "--direct"])

    assert detached.disposition == "discard"
    assert detached.omp_args == ("--model",)
    assert direct.disposition == "direct"
    assert direct.omp_args == ("--thinking",)
    with pytest.raises(LauncherError, match="--direct and --detached cannot be combined"):
        inspect_launch_arguments(["--model", "--detached", "--thinking", "--direct"])


def test_basecamp_flags_after_separator_remain_prompt_content() -> None:
    inspected = inspect_launch_arguments(["prompt", "--", "--direct", "--detached"])

    assert inspected.disposition == "auto"
    assert inspected.omp_args == ("prompt", "--", "--direct", "--detached")


@pytest.mark.parametrize(
    ("args", "source", "value"),
    [
        (["--continue"], "continue", None),
        (["-c"], "continue", None),
        (["--resume", "session-id"], "resume", "session-id"),
        (["--resume=session-id"], "resume", "session-id"),
        (["-r", "session-id"], "resume", "session-id"),
        (["--fork", "session-file"], "fork", "session-file"),
        (["--session=session-file"], "session", "session-file"),
    ],
)
def test_session_sources_are_classified_for_direct_or_managed_resume(
    args: list[str],
    source: str,
    value: str | None,
) -> None:
    inspected = inspect_launch_arguments(args)

    assert inspected.disposition == "direct"
    assert inspected.session_source == source
    assert inspected.session_value == value


def test_plan_mode_keeps_fresh_scratch_placement_until_native_worktree_handoff() -> None:
    inspected = inspect_launch_arguments(["--plan", "reviewer", "prompt"])

    assert inspected.disposition == "auto"
    assert inspected.omp_args == ("--plan", "reviewer", "prompt")


@pytest.mark.parametrize("args", [["--plan-yolo"], ["--plan-yolo-into", "implementation"]])
def test_plan_transition_launch_flags_remain_native_direct(args: list[str]) -> None:
    inspected = inspect_launch_arguments(args)

    assert inspected.disposition == "direct"
    assert inspected.omp_args == tuple(args)


def test_profile_and_session_directory_survive_basecamp_token_removal() -> None:
    inspected = inspect_launch_arguments(
        ["--profile", "review", "--session-dir=relative/sessions", "--direct", "prompt"]
    )

    assert inspected.disposition == "direct"
    assert inspected.profile == "review"
    assert inspected.session_dir == "relative/sessions"
    assert inspected.omp_args == (
        "--profile",
        "review",
        "--session-dir=relative/sessions",
        "prompt",
    )
