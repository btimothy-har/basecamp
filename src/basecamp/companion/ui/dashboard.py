"""Dashboard body: the daemon-derived analysis sections."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Static

from basecamp.companion.analysis import CompanionAnalysis


def _render_bullets(items: list[str]) -> Text:
    """Render items as markup-safe bullet lines, or an em dash when empty."""

    if not items:
        return Text("—", style="dim")

    rendered = Text()
    for index, item in enumerate(items):
        if index:
            rendered.append("\n")
        rendered.append("• ")
        rendered.append(item)
    return rendered


class DashboardBody(Widget):
    """Analysis dashboard: daemon-derived monitor / needs-capture / checkpoints."""

    can_focus = True

    BINDINGS = [
        Binding("m", "app.toggle_mode", "Mode"),
    ]

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._analysis: CompanionAnalysis | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="dashboard-monitor", classes="dashboard-box")
        with Horizontal(id="dashboard-bottom"):
            yield Static(id="dashboard-capture", classes="dashboard-box")
            yield Static(id="dashboard-checkpoints", classes="dashboard-box")

    def render(self) -> Text:
        return Text()

    def on_mount(self) -> None:
        self.query_one("#dashboard-monitor", Static).border_title = "Monitor"
        self.query_one("#dashboard-capture", Static).border_title = "Needs capture"
        self.query_one("#dashboard-checkpoints", Static).border_title = "Checkpoints"
        self._render_sections()

    def update(self, analysis: CompanionAnalysis | None) -> None:
        # A None fetch (daemon unreachable or not ready yet) retains the
        # last-shown sections rather than blanking the panel.
        if analysis is not None:
            self._analysis = analysis
        self._render_sections()

    def _render_sections(self) -> None:
        analysis = self._analysis
        self.query_one("#dashboard-monitor", Static).update(
            _render_bullets(analysis.monitor) if analysis else Text("—", style="dim")
        )
        self.query_one("#dashboard-capture", Static).update(
            _render_bullets(analysis.needs_capture) if analysis else Text("—", style="dim")
        )
        self.query_one("#dashboard-checkpoints", Static).update(
            _render_bullets(analysis.checkpoints) if analysis else Text("—", style="dim")
        )
