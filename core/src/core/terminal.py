"""Terminal multiplexer backends for spawning worker panes.

Supports tmux (via split-window) and Kitty (via remote control over a Unix socket).
Detection is automatic based on environment variables: $KITTY_LISTEN_ON for Kitty,
$TMUX for tmux. Kitty takes priority when both are available.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from core.exceptions import PaneLaunchError


class TmuxBackend:
    """Spawn worker panes via tmux split-window."""

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


class KittyBackend:
    """Spawn worker panes via Kitty remote control over a Unix socket.

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


def detect_backend() -> TmuxBackend | KittyBackend | None:
    """Return the active terminal backend, or None if unavailable.

    Kitty takes priority when both are available because it provides
    native window splitting without needing a tmux wrapper session.
    """
    if KittyBackend.is_active():
        return KittyBackend()
    if TmuxBackend.is_active():
        return TmuxBackend()
    return None


def in_multiplexer() -> bool:
    """Check if we're running inside a terminal multiplexer (Kitty or tmux)."""
    return bool(os.environ.get("KITTY_LISTEN_ON") or os.environ.get("TMUX"))
