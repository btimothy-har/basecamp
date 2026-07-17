"""Tests for basecamp.mcp.render — instructions router + resource bodies."""

from __future__ import annotations

from basecamp.claude.logseq import LogseqAwareness
from basecamp.mcp.render import (
    build_instructions,
    render_cockpit,
    render_context,
    render_dirs,
    render_dossier_index,
)
from basecamp.mcp.resolve import ProjectAwareness


def _available_logseq(
    *,
    cockpit_text: str | None = None,
    dossier_paths: tuple[str, ...] = (),
) -> LogseqAwareness:
    return LogseqAwareness(
        graph_dir="/g",
        identity="acme/web-app",
        cockpit_name="repo__acme__web-app",
        cockpit_path="/g/pages/repo__acme__web-app.md",
        cockpit_text=cockpit_text,
        dossier_prefix="work__acme__web-app__",
        dossier_paths=dossier_paths,
    )


def test_instructions_projected_includes_identity_dirs_and_pointers() -> None:
    awareness = ProjectAwareness(
        project_name="myproj",
        repo_root="/home/u/repo",
        related_dirs=["/home/u/shared"],
    )
    text = build_instructions(awareness)
    assert "# Project: myproj" in text
    assert "/home/u/repo" in text
    assert "/home/u/shared" in text
    assert "basecamp://project/context" in text
    assert "basecamp://project/dirs" in text


def test_instructions_unprojected_is_no_project_message() -> None:
    text = build_instructions(ProjectAwareness(repo_root="/home/u/repo"))
    assert "No basecamp project is configured" in text
    assert "# basecamp" in text


def test_instructions_stay_under_2kb_with_many_long_dirs() -> None:
    dirs = [f"/home/u/very/long/path/segment/number/{i:03d}/workspace" for i in range(200)]
    awareness = ProjectAwareness(project_name="big", repo_root="/home/u/repo", related_dirs=dirs)
    text = build_instructions(awareness)
    assert len(text.encode("utf-8")) <= 2048
    # The inline list is truncated with a pointer to the resource.
    assert "more; see basecamp://project/dirs" in text


def test_render_dirs_with_and_without_dirs() -> None:
    with_dirs = render_dirs(ProjectAwareness(project_name="p", repo_root="/r", related_dirs=["/a", "/b"]))
    assert "/a" in with_dirs and "/b" in with_dirs
    assert "Repository root: /r" in with_dirs

    without = render_dirs(ProjectAwareness(project_name="p", repo_root="/r"))
    assert "No additional directories are configured" in without


def test_render_context_present_and_absent() -> None:
    present = render_context(ProjectAwareness(project_name="p", context_text="# Rules"))
    assert present == "# Rules"

    absent = render_context(ProjectAwareness(project_name="p"))
    assert "No standing project context is configured for p" in absent


def test_render_cockpit_uses_resolver_body_purely() -> None:
    # pure: renders cockpit_text as-is, no filesystem access
    mem = _available_logseq(cockpit_text="# acme/web-app\n\nActive: the auth refactor.\n")
    assert "auth refactor" in render_cockpit(mem)


def test_render_cockpit_seed_stub_when_text_none() -> None:
    body = render_cockpit(_available_logseq(cockpit_text=None))
    assert "not written yet" in body
    assert "repo__acme__web-app" in body


def test_render_cockpit_unavailable() -> None:
    body = render_cockpit(LogseqAwareness(reason="repo identity is unavailable"))
    assert "unavailable" in body.lower()
    assert "Do not scan it to compensate" in body


def test_render_dossier_index_lists_pointers() -> None:
    mem = _available_logseq(
        dossier_paths=(
            "/g/pages/work__acme__web-app__brave-otter-fox.md",
            "/g/pages/work__acme__web-app__calm-river-owl.md",
        ),
    )
    body = render_dossier_index(mem)
    assert "brave-otter-fox" in body
    assert "calm-river-owl" in body
    assert "work__acme__web-app__brave-otter-fox.md" in body


def test_render_dossier_index_empty() -> None:
    assert "No work dossiers exist yet" in render_dossier_index(_available_logseq())
