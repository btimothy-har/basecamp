"""Tests for basecamp.mcp.logseq + the memory renderers.

Resolution must match the (retired) Pi extension's ``pi/core/project/logseq.ts``
(page/dir naming, graph-dir resolution, safe-identity transform). These cover
the resolver, the two renderers, and the graph-absent fallback — all pure,
daemon-independent.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from basecamp.core.settings import Settings
from basecamp.mcp.logseq import MemoryAwareness, resolve_memory, safe_repo_identity
from basecamp.mcp.render import render_cockpit, render_dossier_index


def _write_logseq_config(home: Path, graph_dir: Path) -> Settings:
    config_path = home / ".pi" / "basecamp" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({"logseq": {"graph_dir": str(graph_dir)}}))
    return Settings(config_path)


def _init_repo(path: Path, origin: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", origin], cwd=path, check=True)


def _graph_with_pages(home: Path, *page_names: str) -> Path:
    pages = home / "graph" / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    for name in page_names:
        (pages / f"{name}.md").write_text(f"# {name}\n\ncontent\n")
    return home / "graph"


def test_safe_repo_identity_matches_ts_transform() -> None:
    assert safe_repo_identity("acme/web-app") == "acme__web-app"
    assert safe_repo_identity(" acme/web app ") == "acme__web_app"
    assert safe_repo_identity("a/b/c") == "a__b__c"


def test_resolve_memory_available(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, "https://github.com/acme/web-app.git")
    graph = _graph_with_pages(
        tmp_path,
        "repo__acme__web-app",
        "work__acme__web-app__brave-otter-fox",
        "work__acme__web-app__calm-river-owl",
        "work__other__repo__nope",
    )
    config = _write_logseq_config(tmp_path, graph)

    mem = resolve_memory(str(repo), home=tmp_path, config=config)

    assert mem.available
    assert mem.repo_identity == "acme/web-app"
    assert mem.cockpit_name == "repo__acme__web-app"
    assert mem.cockpit_path == str(graph / "pages" / "repo__acme__web-app.md")
    assert mem.dossier_prefix == "work__acme__web-app__"
    # only this repo's dossiers, sorted; the other-repo page is excluded
    assert mem.dossier_paths == (
        str(graph / "pages" / "work__acme__web-app__brave-otter-fox.md"),
        str(graph / "pages" / "work__acme__web-app__calm-river-owl.md"),
    )


def test_resolve_memory_graph_absent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, "https://github.com/acme/web-app.git")
    # graph_dir points at a nonexistent directory -> unavailable
    config = _write_logseq_config(tmp_path, tmp_path / "does-not-exist")

    mem = resolve_memory(str(repo), home=tmp_path, config=config)

    assert not mem.available
    assert mem.graph_dir is None
    assert mem.repo_identity == "acme/web-app"
    assert mem.reason is not None


def test_resolve_memory_no_repo(tmp_path: Path) -> None:
    # a non-repo cwd -> no identity -> unavailable
    plain = tmp_path / "plain"
    plain.mkdir()
    graph = _graph_with_pages(tmp_path)
    config = _write_logseq_config(tmp_path, graph)

    mem = resolve_memory(str(plain), home=tmp_path, config=config)

    assert not mem.available
    assert mem.repo_identity is None


def test_render_cockpit_reads_body(tmp_path: Path) -> None:
    graph = _graph_with_pages(tmp_path, "repo__acme__web-app")
    cockpit = graph / "pages" / "repo__acme__web-app.md"
    cockpit.write_text("# acme/web-app\n\nActive: the auth refactor.\n")
    mem = MemoryAwareness(
        graph_dir=str(graph),
        repo_identity="acme/web-app",
        cockpit_name="repo__acme__web-app",
        cockpit_path=str(cockpit),
        dossier_prefix="work__acme__web-app__",
    )
    assert "auth refactor" in render_cockpit(mem)


def test_render_cockpit_seed_stub_when_missing(tmp_path: Path) -> None:
    graph = _graph_with_pages(tmp_path)
    mem = MemoryAwareness(
        graph_dir=str(graph),
        repo_identity="acme/web-app",
        cockpit_name="repo__acme__web-app",
        cockpit_path=str(graph / "pages" / "repo__acme__web-app.md"),
        dossier_prefix="work__acme__web-app__",
    )
    body = render_cockpit(mem)
    assert "not written yet" in body
    assert "repo__acme__web-app" in body


def test_render_cockpit_unavailable() -> None:
    mem = MemoryAwareness(reason="repo identity is unavailable")
    body = render_cockpit(mem)
    assert "unavailable" in body.lower()
    assert "Do not scan the Logseq graph" in body


def test_render_dossier_index_lists_pointers(tmp_path: Path) -> None:
    graph = tmp_path / "graph"
    (graph / "pages").mkdir(parents=True)
    mem = MemoryAwareness(
        graph_dir=str(graph),
        repo_identity="acme/web-app",
        cockpit_name="repo__acme__web-app",
        cockpit_path=str(graph / "pages" / "repo__acme__web-app.md"),
        dossier_prefix="work__acme__web-app__",
        dossier_paths=(
            str(graph / "pages" / "work__acme__web-app__brave-otter-fox.md"),
            str(graph / "pages" / "work__acme__web-app__calm-river-owl.md"),
        ),
    )
    body = render_dossier_index(mem)
    assert "brave-otter-fox" in body
    assert "calm-river-owl" in body
    # pointers, not bodies
    assert "work__acme__web-app__brave-otter-fox.md" in body


def test_render_dossier_index_empty(tmp_path: Path) -> None:
    graph = tmp_path / "graph"
    mem = MemoryAwareness(
        graph_dir=str(graph),
        repo_identity="acme/web-app",
        cockpit_name="repo__acme__web-app",
        cockpit_path=str(graph / "pages" / "repo__acme__web-app.md"),
        dossier_prefix="work__acme__web-app__",
    )
    assert "No work dossiers exist yet" in render_dossier_index(mem)
