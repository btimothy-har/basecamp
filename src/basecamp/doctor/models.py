"""Typed contracts shared by Basecamp doctor checks and repairs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Severity(StrEnum):
    """Public diagnostic severity."""

    PASS = "pass"
    INFO = "info"
    WARNING = "warning"
    REPAIRABLE = "repairable"
    ERROR = "error"


class RepairKind(StrEnum):
    """Bounded repair categories shown in a doctor plan."""

    CONFIG = "config"
    LAYOUT = "layout"
    DATABASE = "database"
    ARCHIVE = "archive"


@dataclass(frozen=True)
class RepairAction:
    """One planned repair, without executable behavior."""

    code: str
    kind: RepairKind
    description: str
    paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class DoctorCheck:
    """One stable, user-facing doctor result."""

    section: str
    code: str
    severity: Severity
    message: str
    path: Path | None = None

    @property
    def identifier(self) -> str:
        return f"{self.section}.{self.code}"


@dataclass
class DoctorReport:
    """Collected checks, repair plan, and optional recovery archive."""

    checks: list[DoctorCheck] = field(default_factory=list)
    actions: list[RepairAction] = field(default_factory=list)
    archive_path: Path | None = None

    def add_check(self, check: DoctorCheck) -> None:
        self.checks.append(check)

    def add_action(self, action: RepairAction) -> None:
        self.actions.append(action)

    def extend(self, other: DoctorReport) -> None:
        self.checks.extend(other.checks)
        self.actions.extend(other.actions)
        if other.archive_path is not None:
            self.archive_path = other.archive_path

    @property
    def has_unresolved(self) -> bool:
        return any(check.severity in {Severity.REPAIRABLE, Severity.ERROR} for check in self.checks)

    @property
    def exit_code(self) -> int:
        return 1 if self.has_unresolved else 0


@dataclass(frozen=True)
class DoctorPaths:
    """All local paths the doctor is allowed to inspect or repair."""

    home: Path
    root: Path
    config: Path
    config_lock: Path
    archive_root: Path
    swarm: Path
    daemon_db: Path
    daemon_socket: Path
    daemon_pid: Path
    daemon_spawn_lock: Path

    @classmethod
    def for_home(cls, home: Path) -> DoctorPaths:
        resolved_home = home.expanduser()
        root = resolved_home / ".pi" / "basecamp"
        config = root / "config.json"
        swarm = root / "swarm"
        return cls(
            home=resolved_home,
            root=root,
            config=config,
            config_lock=config.with_suffix(".lock"),
            archive_root=root / "backups" / "doctor",
            swarm=swarm,
            daemon_db=swarm / "daemon.db",
            daemon_socket=swarm / "daemon.sock",
            daemon_pid=swarm / "daemon.pid",
            daemon_spawn_lock=swarm / "daemon.spawn.lock",
        )
