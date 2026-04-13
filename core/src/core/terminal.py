"""Terminal backends for session execution and worker pane spawning.

Each backend handles two concerns:
- exec_session: Replace the current process with a session, displaying the
  startup banner and forwarding environment variables.
- spawn_pane: Create a new terminal pane for a dispatch worker.

Detection is automatic based on environment variables: $KITTY_LISTEN_ON for Kitty,
$TMUX for tmux. Kitty takes priority when both are available.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from core.exceptions import PaneLaunchError


class TerminalBackend:
    """Base class for terminal backends.

    Provides the default exec_session implementation (print header + execvp).
    Subclasses add spawn_pane for multiplexer-based pane creation.
    """

    name: str = "base"

    def exec_session(
        self,
        cmd: list[str],
        *,
        startup_text: str,
        env_vars: dict[str, str],
        session_name: str,  # noqa: ARG002
    ) -> None:
        """Replace the current process with a session.

        Exports env_vars into the current process, prints the startup banner,
        then execvp into the command.
        """
        for key, value in env_vars.items():
            os.environ[key] = value
        print(startup_text, end="")
        os.execvp(cmd[0], cmd)


class TmuxBackend(TerminalBackend):
    """Terminal backend for tmux sessions.

    Uses the default exec_session (print + execvp) when already inside tmux.
    Provides spawn_pane via tmux split-window for dispatch workers.
    """

    name = "tmux"

    @staticmethod
    def is_active() -> bool:
        return bool(os.environ.get("TMUX"))

    def spawn_pane(
        self,
        script: str | Path,
        *,
        env: dict[str, str],
        cwd: Path,
        title: str,
    ) -> None:
        cmd = [
            "tmux",
            "split-window",
            "-v",
            "-P",
            "-F",
            "#{pane_id}",
        ]
        for key, value in env.items():
            cmd.extend(["-e", f"{key}={value}"])
        cmd.extend(["-c", str(cwd), str(script)])

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise PaneLaunchError(self.name, e.stderr) from e

        # Set pane title (non-critical)
        pane_id = result.stdout.strip()
        if pane_id:
            try:
                subprocess.run(
                    ["tmux", "select-pane", "-t", pane_id, "-T", title],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError:
                pass


class KittyBackend(TerminalBackend):
    """Terminal backend for Kitty.

    Uses the default exec_session (print + execvp). Spawns panes via
    Kitty remote control over a Unix socket.

    Requires `allow_remote_control` and `listen_on` in kitty.conf.
    The socket path is read from $KITTY_LISTEN_ON, which Kitty sets
    automatically in all child processes when `listen_on` is configured.
    """

    name = "kitty"

    @staticmethod
    def is_active() -> bool:
        return bool(os.environ.get("KITTY_LISTEN_ON"))

    def spawn_pane(
        self,
        script: str | Path,
        *,
        env: dict[str, str],
        cwd: Path,
        title: str,
    ) -> None:
        socket = os.environ["KITTY_LISTEN_ON"]
        cmd = [
            "kitty",
            "@",
            "--to",
            socket,
            "launch",
            "--type=window",
            "--keep-focus",
            "--copy-env",
            "--cwd",
            str(cwd),
            "--title",
            title,
        ]
        for key, value in env.items():
            cmd.extend(["--env", f"{key}={value}"])
        cmd.append(str(script))

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise PaneLaunchError(self.name, e.stderr) from e


def resolve_launch_backend() -> TerminalBackend:
    """Resolve the backend for launching a session.

    All backends use the same exec_session (export env vars + print + execvp).
    The distinction only matters for knowing which multiplexer is active.
    """
    if KittyBackend.is_active():
        return KittyBackend()
    if TmuxBackend.is_active():
        return TmuxBackend()
    return TerminalBackend()


def resolve_dispatch_backend() -> TmuxBackend | KittyBackend | None:
    """Resolve the backend for spawning dispatch worker panes.

    Requires an active multiplexer session. Returns None if unavailable.
    Kitty takes priority when both are available because it provides
    native window splitting without needing a tmux wrapper session.
    """
    if KittyBackend.is_active():
        return KittyBackend()
    if TmuxBackend.is_active():
        return TmuxBackend()
    return None
