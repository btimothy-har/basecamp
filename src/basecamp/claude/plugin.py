"""Register the basecamp plugin into Claude Code so a bare ``claude`` loads it.

Registration goes through the ``claude`` CLI itself — deliberately **not** by
hand-writing ``~/.claude/settings.json``. Writing ``extraKnownMarketplaces`` +
``enabledPlugins`` into settings.json *looks* right (it is exactly what
``claude plugin install`` leaves behind), but it does **not** load the plugin:
Claude Code only loads a plugin whose files it has copied into its local cache
(``~/.claude/plugins/cache``), and that cache is built by ``claude plugin
install`` — it is not reconciled from settings.json at session start. Verified
empirically (settings.json alone → the ``SessionStart`` hook never fires) and
consistent with the plugins reference (plugins are copied to the cache for
verification rather than used in place).

So we drive Claude Code's own machinery, which writes settings.json **and** builds
the cache, and stays forward-compatible if that internal layout ever changes::

    claude plugin marketplace add    <install_dir>/claude   # register the local marketplace
    claude plugin install            basecamp@basecamp       # install + enable (builds the cache)
    claude plugin marketplace update basecamp                # refresh marketplace metadata from source
    claude plugin update             basecamp@basecamp       # apply the refreshed source

All four commands are idempotent, so ``basecamp install`` stays re-runnable — and
a re-run picks up plugin edits made since the last install (the two ``update``
steps refresh the cache from the on-disk source).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

#: Marketplace name registered for basecamp's own ``claude/`` directory. Matches
#: the ``name`` in ``claude/.claude-plugin/marketplace.json``.
MARKETPLACE_NAME = "basecamp"

#: Plugin name (from ``claude/.claude-plugin/plugin.json``).
PLUGIN_NAME = "basecamp"

#: The ``<plugin>@<marketplace>`` id the ``claude plugin`` commands take.
ENABLED_KEY = f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"

#: Per-command budget. Guards against a first-run prompt hanging the otherwise
#: non-interactive install; the local-directory commands complete in well under
#: a second in practice.
_CLAUDE_TIMEOUT_S = 120


class PluginRegistrationError(RuntimeError):
    """Raised when the plugin cannot be registered via the ``claude`` CLI."""


def plugin_dir(install_dir: Path) -> Path:
    """Return the plugin directory (``<install_dir>/claude``) as an absolute path."""
    return (Path(install_dir) / "claude").resolve()


def _claude_bin() -> str:
    """Locate the ``claude`` executable, or raise a caller-friendly error."""
    claude = shutil.which("claude")
    if claude is None:
        msg = "the `claude` CLI is not on PATH (install Claude Code, then re-run `basecamp install`)"
        raise PluginRegistrationError(msg)
    return claude


def _run_plugin_command(claude: str, *args: str) -> None:
    """Run one ``claude plugin ...`` command, raising on failure/timeout."""
    label = "claude plugin " + " ".join(args)
    try:
        result = subprocess.run(
            [claude, "plugin", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=_CLAUDE_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        msg = f"`{label}` could not run: {exc}"
        raise PluginRegistrationError(msg) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        msg = f"`{label}` exited {result.returncode}: {detail}"
        raise PluginRegistrationError(msg)


def register_plugin(install_dir: Path) -> None:
    """Register + enable the basecamp plugin via the ``claude`` CLI.

    Drives ``claude plugin marketplace add/update`` + ``plugin install/update`` so
    Claude Code writes ``~/.claude/settings.json`` **and** builds the
    ``~/.claude/plugins`` cache the loader actually reads. Idempotent and
    refresh-on-re-run. Raises :class:`PluginRegistrationError` if ``claude`` is
    absent or any step fails.
    """
    claude = _claude_bin()
    marketplace_source = str(plugin_dir(install_dir))
    _run_plugin_command(claude, "marketplace", "add", marketplace_source)
    _run_plugin_command(claude, "install", ENABLED_KEY)
    _run_plugin_command(claude, "marketplace", "update", MARKETPLACE_NAME)
    _run_plugin_command(claude, "update", ENABLED_KEY)
