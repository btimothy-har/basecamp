"""Tests for basecamp.claude.logseq — shared-Logseq page resolution.

Resolution must match the (retired) Pi extension's ``pi/core/project/logseq.ts``
(page/dir naming, graph-dir resolution, safe-identity transform). The resolver
reads the cockpit body into ``cockpit_text`` so the renderers stay pure.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from basecamp.claude.config import ClaudeConfig
from basecamp.claude.logseq import resolve_config_path, resolve_logseq, safe_identity
from basecamp.claude.paths import config_path


def _write_logseq_config(home: Path, graph_dir: Path) -> ClaudeConfig:
    path = config_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"logseq": {"graph_dir": str(graph_dir)}}))
    return ClaudeConfig(home=home)


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


def test_safe_identity_matches_ts_transform() -> None:
    assert safe_identity("acme/web-app") == "acme__web-app"
    assert safe_identity(" acme/web app ") == "acme__web_app"
    assert safe_identity("a/b/c") == "a__b__c"


def test_resolve_config_path_rules(tmp_path: Path) -> None:
    assert resolve_config_path("~", tmp_path) == str(tmp_path)
    assert resolve_config_path("~/g", tmp_path) == str(tmp_path / "g")
    assert resolve_config_path("/abs/x", tmp_path) == "/abs/x"
    assert resolve_config_path("rel", tmp_path) == str(tmp_path / "rel")  # never cwd


def test_resolve_logseq_available_reads_cockpit_body(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, "https://github.com/acme/web-app.git")
    graph = _graph_with_pages(
        tmp_path,
        "repo__acme__web-app",
        "work__acme__web-app__brave-otter-fox",
        "work__acme__web-app__calm-river-owl",
        "work__other__repo__nope",
    )
    (graph / "pages" / "repo__acme__web-app.md").write_text("# cockpit\n\nActive: auth refactor.\n")
    config = _write_logseq_config(tmp_path, graph)

    mem = resolve_logseq(str(repo), home=tmp_path, config=config)

    assert mem.available
    assert mem.identity == "acme/web-app"
    assert mem.cockpit_name == "repo__acme__web-app"
    assert mem.cockpit_path == str(graph / "pages" / "repo__acme__web-app.md")
    assert mem.cockpit_text is not None and "auth refactor" in mem.cockpit_text
    assert mem.dossier_prefix == "work__acme__web-app__"
    assert mem.dossier_paths == (
        str(graph / "pages" / "work__acme__web-app__brave-otter-fox.md"),
        str(graph / "pages" / "work__acme__web-app__calm-river-owl.md"),
    )


def test_resolve_logseq_cockpit_absent_leaves_text_none(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, "https://github.com/acme/web-app.git")
    graph = _graph_with_pages(tmp_path)  # no cockpit page written
    config = _write_logseq_config(tmp_path, graph)

    mem = resolve_logseq(str(repo), home=tmp_path, config=config)

    assert mem.available
    assert mem.cockpit_text is None  # resolver read; renderer emits the seed stub


def test_resolve_logseq_graph_absent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, "https://github.com/acme/web-app.git")
    config = _write_logseq_config(tmp_path, tmp_path / "does-not-exist")

    mem = resolve_logseq(str(repo), home=tmp_path, config=config)

    assert not mem.available
    assert mem.graph_dir is None
    assert mem.identity == "acme/web-app"
    assert mem.reason is not None


def test_resolve_logseq_no_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    graph = _graph_with_pages(tmp_path)
    config = _write_logseq_config(tmp_path, graph)

    mem = resolve_logseq(str(plain), home=tmp_path, config=config)

    assert not mem.available
    assert mem.identity is None
