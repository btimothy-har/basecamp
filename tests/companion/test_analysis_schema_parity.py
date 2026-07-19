"""CI parity between the hub daemon's analysis schema and the companion's.

The two ``AnalysisSections`` models are deliberately separate: the hub's broker
owns its schema (self-contained, no companion dependency) and the companion parses
the ``GET /analysis`` JSON into its own. They meet only over a camelCase JSON wire,
so this test keeps the two ends in lockstep — same fields, same aliases, same cap,
and a hub-serialize -> companion-validate round-trip — catching drift at CI time
rather than as a silent dash in the dashboard.
"""

from __future__ import annotations

from basecamp.companion.analysis import MAX_SECTION_ITEMS as COMPANION_MAX
from basecamp.companion.analysis import AnalysisSections as CompanionSections
from basecamp.companion.analysis import CompanionAnalysis
from basecamp.hub.broker.analysis.sections import MAX_SECTION_ITEMS as HUB_MAX
from basecamp.hub.broker.analysis.sections import AnalysisSections as HubSections

_SECTION_FIELDS = {"monitor", "needs_capture", "checkpoints"}


def test_section_fields_match() -> None:
    assert set(HubSections.model_fields) == _SECTION_FIELDS
    assert set(CompanionSections.model_fields) == _SECTION_FIELDS


def test_section_json_aliases_match() -> None:
    hub_aliases = {name: field.alias for name, field in HubSections.model_fields.items()}
    companion_aliases = {name: field.alias for name, field in CompanionSections.model_fields.items()}
    assert hub_aliases == companion_aliases
    assert hub_aliases["needs_capture"] == "needsCapture"


def test_section_cap_matches() -> None:
    assert HUB_MAX == COMPANION_MAX


def test_hub_output_round_trips_into_companion_model() -> None:
    over_cap = [f"c{index}" for index in range(HUB_MAX + 2)]
    hub = HubSections(
        monitor=["watch the migration"],
        needs_capture=["prefers the hub name"],
        checkpoints=over_cap,
    )
    payload = hub.model_dump(by_alias=True)

    parsed = CompanionAnalysis.model_validate(payload)
    assert parsed.monitor == ["watch the migration"]
    assert parsed.needs_capture == ["prefers the hub name"]
    # both sides cap over-long sections at MAX_SECTION_ITEMS
    assert len(parsed.checkpoints) == HUB_MAX
