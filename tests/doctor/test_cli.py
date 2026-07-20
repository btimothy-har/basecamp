"""CLI routing and rendering for ``basecamp doctor``."""

from __future__ import annotations

from click.testing import CliRunner

import basecamp.cli as root_cli
import basecamp.doctor.cli as doctor_cli
from basecamp.doctor.models import DoctorCheck, DoctorReport, Severity


def test_doctor_is_a_top_level_command() -> None:
    assert "doctor" in root_cli.basecamp.commands
    result = CliRunner().invoke(root_cli.basecamp, ["doctor", "--help"])
    assert result.exit_code == 0
    assert "--repair" in result.output


def test_doctor_routes_repair_and_returns_report_status(monkeypatch) -> None:
    repair_values: list[bool] = []

    def run_doctor(_paths, *, repair: bool) -> DoctorReport:
        repair_values.append(repair)
        return DoctorReport(checks=[DoctorCheck("config", "invalid", Severity.ERROR, "Invalid config")])

    monkeypatch.setattr(doctor_cli, "run_doctor", run_doctor)

    result = CliRunner().invoke(root_cli.basecamp, ["doctor", "--repair"])

    assert repair_values == [True]
    assert result.exit_code == 1
    assert "Invalid config" in result.output
    assert "unresolved issues" in result.output


def test_doctor_renders_healthy_report(monkeypatch) -> None:
    def healthy_report(_paths, *, repair: bool) -> DoctorReport:
        assert repair is False
        return DoctorReport(checks=[DoctorCheck("layout", "root", Severity.PASS, "Root is healthy")])

    monkeypatch.setattr(doctor_cli, "run_doctor", healthy_report)

    result = CliRunner().invoke(root_cli.basecamp, ["doctor"])

    assert result.exit_code == 0
    assert "Root is healthy" in result.output
    assert "local state is healthy" in result.output
