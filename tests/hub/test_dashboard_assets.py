"""Static dashboard asset packaging and security invariants."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[2] / "src/basecamp/hub/dashboard/assets"

STYLESHEETS = [
    "styles.css",
    "controls.css",
    "chrome.css",
    "session-rail.css",
    "detail-shared.css",
    "goal-stages.css",
    "agent-topology.css",
    "run-detail.css",
    "states.css",
    "responsive.css",
]

RENDER_MODULES = {
    "render.js",
    "render-ui.js",
    "render-rail.js",
    "render-goal-stages.js",
    "render-topology.js",
    "render-session.js",
    "render-agent.js",
    "render-run-detail.js",
}


class _DocumentAssets(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []
        self.inline_scripts: list[str] = []
        self._in_script_without_src = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script":
            source = values.get("src")
            if source:
                self.references.append(source)
            else:
                self._in_script_without_src = True
        if tag == "link" and values.get("rel") in {"stylesheet", "icon"} and values.get("href"):
            self.references.append(values["href"])

    def handle_data(self, data: str) -> None:
        if self._in_script_without_src and data.strip():
            self.inline_scripts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script_without_src = False


def test_dashboard_html_is_semantic_small_and_external_only() -> None:
    html = (ASSETS / "index.html").read_text(encoding="utf-8")
    parser = _DocumentAssets()
    parser.feed(html)

    assert len(html.splitlines()) < 500
    assert {"<header", "<section", "<aside", "<nav", "<main"} <= {
        token for token in ("<header", "<section", "<aside", "<nav", "<main") if token in html
    }
    assert parser.inline_scripts == []
    assert parser.references
    assert re.findall(r'<link rel="stylesheet" href="/assets/([^"/]+)">', html) == STYLESHEETS
    for reference in parser.references:
        assert reference.startswith("/assets/")
        assert (ASSETS / reference.removeprefix("/assets/")).is_file()


def test_dashboard_modules_are_flat_self_contained_and_avoid_html_sinks() -> None:
    scripts = list(ASSETS.glob("*.js"))
    assert (ASSETS / "favicon.svg").is_file()
    assert {path.name for path in scripts} >= {"app.js", "dom.js", "model.js", *RENDER_MODULES}
    sources = {path.name: path.read_text(encoding="utf-8") for path in scripts}
    combined = "\n".join(sources.values())
    exports_by_script = {
        name: set(re.findall(r"export\s+(?:const|function|class)\s+(\w+)", source))
        for name, source in sources.items()
    }
    imports_by_script: dict[str, set[str]] = {}

    for name, source in sources.items():
        imports = set(re.findall(r'from\s+["\']/assets/([^"\']+)["\']', source))
        imports_by_script[name] = {dependency for dependency in imports if dependency.endswith(".js")}
        for import_path in imports:
            assert (ASSETS / import_path).is_file()
        for imported_names, import_path in re.findall(
            r'import\s*{([^}]+)}\s*from\s*["\']/assets/([^"\']+)["\']', source, re.DOTALL
        ):
            names = {item.strip().split(" as ", 1)[0] for item in imported_names.split(",") if item.strip()}
            assert names <= exports_by_script[import_path]

    assert imports_by_script["app.js"] == {"model.js", "render.js"}
    assert 'import { renderDashboard } from "/assets/render.js";' in sources["app.js"]

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        assert name not in visiting, f"dashboard module cycle at {name}"
        if name in visited:
            return
        visiting.add(name)
        for dependency in imports_by_script[name]:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for name in imports_by_script:
        visit(name)

    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "new Function", "serviceWorker"):
        assert forbidden not in combined
    assert "http://" not in combined
    assert "https://" not in combined
