"""basecamp MCP context server — Tier-0 project awareness for Claude Code.

A stdio MCP server, spawned per Claude Code session, that injects the current
project's related directories and curated context. It reuses the config schema
owner (:mod:`basecamp.core.projects`) so the plugin never drifts from the
writer of ``~/.pi/basecamp/config.json``.
"""
