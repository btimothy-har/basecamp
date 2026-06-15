"""Command line interface for the Basecamp swarm runtime."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .server import run_daemon

DEFAULT_UDS_PATH = Path("~/.pi/agent/basecamp/daemon.sock").expanduser()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bc-swarm",
        description="Basecamp async-agent swarm runtime.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    daemon = subparsers.add_parser("daemon", help="Run the async-agent daemon.")
    daemon.add_argument(
        "--uds",
        type=Path,
        default=DEFAULT_UDS_PATH,
        help="Unix domain socket path for the daemon listener.",
    )
    daemon.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Optional SQLite database path.",
    )
    daemon.add_argument(
        "--pidfile",
        type=Path,
        default=None,
        help="Optional path to write the daemon PID file.",
    )
    return parser


def _path_value(path: Path | None) -> str | None:
    if path is None:
        return None
    return str(path)


def _run_daemon(args: argparse.Namespace) -> None:
    run_daemon(
        str(args.uds),
        _path_value(args.db),
        _path_value(args.pidfile),
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "daemon":
        _run_daemon(args)


if __name__ == "__main__":
    main()
