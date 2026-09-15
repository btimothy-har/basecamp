"""Path-resolution parity tests for disposable OMP worktrees."""

from __future__ import annotations

from pathlib import Path

from basecamp.omp import detached_plan


def test_default_agent_directory_keeps_xdg_worktree_root(tmp_path: Path) -> None:
    home = tmp_path / "home"
    xdg_root = tmp_path / "xdg" / "omp"
    xdg_root.mkdir(parents=True)

    result = detached_plan._default_worktree_base(
        None,
        {
            "PI_CODING_AGENT_DIR": str(home / ".omp" / "agent"),
            "XDG_DATA_HOME": str(tmp_path / "xdg"),
        },
        home,
        tmp_path,
    )

    assert result == xdg_root / "wt"


def test_relative_custom_agent_directory_disables_xdg(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = tmp_path / "source"
    xdg_root = tmp_path / "xdg" / "omp"
    source.mkdir()
    xdg_root.mkdir(parents=True)

    result = detached_plan._default_worktree_base(
        None,
        {
            "PI_CODING_AGENT_DIR": "custom-agent",
            "XDG_DATA_HOME": str(tmp_path / "xdg"),
        },
        home,
        source,
    )

    assert result == (home / ".omp" / "wt").resolve()


def test_profile_derived_agent_directory_does_not_disable_default_xdg(tmp_path: Path) -> None:
    home = tmp_path / "home"
    xdg_root = tmp_path / "xdg" / "omp"
    xdg_root.mkdir(parents=True)

    result = detached_plan._default_worktree_base(
        None,
        {
            "OMP_PROFILE": "",
            "PI_PROFILE": "review",
            "PI_CODING_AGENT_DIR": str(home / ".omp" / "profiles" / "review" / "agent"),
            "XDG_DATA_HOME": str(tmp_path / "xdg"),
        },
        home,
        tmp_path,
    )

    assert result == xdg_root / "wt"


def test_worktree_base_expands_omp_backslash_home_form(tmp_path: Path) -> None:
    home = tmp_path / "home"

    result = detached_plan._absolute_omp_path(r"~\managed", home)

    assert result == Path(f"{home}\\managed").resolve()
