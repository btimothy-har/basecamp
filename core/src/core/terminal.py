"""Terminal backends for session execution and worker pane spawning.

Each backend handles two concerns:
- exec_session: Replace the current process with a Claude session, displaying the
  startup banner and forwarding environment variables appropriately.
- spawn_pane: Create a new terminal pane for a dispatch worker.

Detection is automatic based on environment variables: $KITTY_LISTEN_ON for Kitty,
$TMUX for tmux. Kitty takes priority when both are available.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

from core.exceptions import PaneLaunchError


class TerminalBackend:
    """Base class for terminal backends.

    Provides the default exec_session implementation (print header + execvp).
    Subclasses override exec_session for backend-specific behavior (e.g. tmux wrapping)
    and add spawn_pane for multiplexer-based pane creation.
    """

    name: str = "base"

    def exec_session(
        self,
        cmd: list[str],
        *,
        startup_text: str,
        env_vars: dict[str, str],  # noqa: ARG002
        session_name: str,  # noqa: ARG002
    ) -> None:
        """Replace the current process with a Claude session.

        Default: print startup banner to stdout, then execvp into claude.
        Subclasses may use env_vars and session_name for backend-specific behavior.
        """
        print(startup_text, end="")
        os.execvp(cmd[0], cmd)


class TmuxBackend(TerminalBackend):
    """Terminal backend for tmux sessions.

    Operates in two modes:
    - Active (wrap=False): Already inside tmux. Uses the default exec_session
      (print header + execvp). Spawns panes via split-window.
    - Wrapping (wrap=True): Not inside any multiplexer. Creates a new tmux
      session with the header and claude command inside a shell wrapper, so
      the header appears within the tmux session rather than the outer terminal.
    """

    name = "tmux"

    def __init__(self, *, wrap: bool = False) -> None:
        self._wrap = wrap

    @staticmethod
    def is_active() -> bool:
        return bool(os.environ.get("TMUX"))

    def exec_session(
        self,
        cmd: list[str],
        *,
        startup_text: str,
        env_vars: dict[str, str],
        session_name: str,
    ) -> None:
        if not self._wrap:
            super().exec_session(cmd, startup_text=startup_text, env_vars=env_vars, session_name=session_name)
            return

        tmux_cmd = ["tmux", "new-session", "-A", "-s", session_name]
        for key, value in env_vars.items():
            tmux_cmd.extend(["-e", f"{key}={value}"])
        # Print startup text inside the tmux session (not the outer terminal
        # where it would be hidden once tmux takes over the display).
        inner = f"printf %s {shlex.quote(startup_text)} && exec {shlex.join(cmd)}"
        tmux_cmd.extend(["sh", "-c", inner])
        os.execvp("tmux", tmux_cmd)

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


class DirectBackend(TerminalBackend):
    """Fallback backend when no terminal multiplexer is available.

    Uses the default exec_session (print + execvp). Cannot spawn panes.
    """

    name = "direct"


def resolve_launch_backend() -> TerminalBackend:
    """Resolve the backend for launching a Claude session.

    Priority: Kitty > active tmux > tmux wrapping > direct fallback.
    """
    if KittyBackend.is_active():
        return KittyBackend()
    if TmuxBackend.is_active():
        return TmuxBackend()
    if shutil.which("tmux"):
        return TmuxBackend(wrap=True)
    return DirectBackend()


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
