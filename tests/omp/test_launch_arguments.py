"""Behavioral tests for Basecamp-owned OMP launch arguments."""

from __future__ import annotations

import pytest

from basecamp.core.exceptions import LauncherError
from basecamp.omp.launch_arguments import (
    inspect_launch_arguments,
    resolve_relocated_path_arguments,
    resolve_session_dir_environment,
)


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
    "args",
    [
        ["--continue"],
        ["-c"],
        ["--resume", "session-id"],
        ["--resume=session-id"],
        ["-r", "session-id"],
        ["--fork", "session-file"],
        ["--session=session-file"],
    ],
)
def test_session_sources_use_native_direct_launch(args: list[str]) -> None:
    inspected = inspect_launch_arguments(args)

    assert inspected.disposition == "direct"
    assert inspected.omp_args == tuple(args)


def test_plan_mode_keeps_fresh_scratch_placement_until_native_worktree_handoff() -> None:
    inspected = inspect_launch_arguments(["--plan", "reviewer", "prompt"])

    assert inspected.disposition == "auto"
    assert inspected.omp_args == ("--plan", "reviewer", "prompt")


@pytest.mark.parametrize(
    "args",
    [
        ["--plan-yolo"],
        ["--plan-yolo-into", "implementation"],
        ["--print"],
        ["-p"],
        ["--help"],
        ["-h"],
        ["--version"],
        ["-v"],
    ],
)
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
    assert inspected.omp_args == (
        "--profile",
        "review",
        "--session-dir=relative/sessions",
        "prompt",
    )


def test_environment_session_directory_is_anchored_before_relocation(tmp_path) -> None:
    environment, resolved = resolve_session_dir_environment(
        {"PI_CODING_AGENT_SESSION_DIR": "sessions"},
        tmp_path / "source" / "nested",
    )

    expected = str((tmp_path / "source" / "nested" / "sessions").resolve())
    assert resolved == expected
    assert environment["PI_CODING_AGENT_SESSION_DIR"] == expected


def test_relocated_path_arguments_remain_anchored_to_source_cwd(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "prompt.md").write_text("system")

    resolved = resolve_relocated_path_arguments(
        [
            "--add-dir",
            "shared",
            "--extension=plugins/ext.ts",
            "--system-prompt",
            "prompt.md",
            "--append-system-prompt",
            "literal prompt",
            "@notes.md",
            "--custom-target",
            "@extension-owned",
            "--",
            "@literal-message",
        ],
        source,
    )

    assert resolved == (
        "--add-dir",
        str(source / "shared"),
        f"--extension={source / 'plugins' / 'ext.ts'}",
        "--system-prompt",
        str(source / "prompt.md"),
        "--append-system-prompt",
        "literal prompt",
        f"@{source / 'notes.md'}",
        "--custom-target",
        "@extension-owned",
        "--",
        "@literal-message",
    )
