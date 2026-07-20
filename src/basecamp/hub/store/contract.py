"""Expected-present SQLite contract for the current hub Store."""

from __future__ import annotations

STORE_USER_VERSION = 1

REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "agents": frozenset(
        {
            "id",
            "parent_id",
            "sibling_group",
            "depth",
            "role",
            "session_name",
            "cwd",
            "created_at",
            "last_seen_at",
            "current_run_id",
            "agent_handle",
            "agent_type",
            "model",
            "session_file",
            "repo",
            "worktree_label",
        }
    ),
    "runs": frozenset(
        {
            "id",
            "agent_id",
            "status",
            "dispatcher_id",
            "spec_json",
            "report_token_hash",
            "result",
            "error",
            "exit_code",
            "pgid",
            "created_at",
            "started_at",
            "ended_at",
        }
    ),
    "run_events": frozenset({"run_id", "seq", "kind", "payload_json", "ts"}),
    "messages": frozenset(
        {
            "id",
            "root_id",
            "sender_node_id",
            "sender_handle",
            "target_agent_id",
            "target_handle",
            "content",
            "interrupt",
            "status",
            "error",
            "created_at",
            "sent_at",
            "queued_at",
            "failed_at",
        }
    ),
    "workstreams": frozenset(
        {
            "id",
            "slug",
            "label",
            "brief",
            "constraints",
            "source_dossier_path",
            "source_repo_page_path",
            "status",
            "version",
            "created_at",
            "updated_at",
        }
    ),
    "workstream_versions": frozenset({"workstream_id", "version", "label", "brief", "constraints", "created_at"}),
    "workstream_agents": frozenset(
        {"workstream_id", "agent_id", "repo", "worktree_label", "status", "error", "joined_at"}
    ),
    "raw_pi_thread": frozenset({"owner_id", "session_id", "session_file", "leaf_id", "latest_seq", "updated_at"}),
    "raw_pi_thread_node": frozenset({"owner_id", "entry_id", "parent_id", "first_seen_seq", "entry_json"}),
    "analysis": frozenset({"owner_id", "based_on_thread_seq", "model", "sections_json", "updated_at"}),
}

MIGRATABLE_COLUMNS: dict[str, frozenset[str]] = {
    "agents": frozenset(
        {"current_run_id", "agent_handle", "agent_type", "model", "session_file", "repo", "worktree_label"}
    ),
    "runs": frozenset({"dispatcher_id", "report_token_hash", "exit_code", "pgid"}),
    "workstreams": frozenset({"version"}),
}

REQUIRED_INDEXES: dict[str, frozenset[str]] = {
    "agents": frozenset({"idx_agents_agent_handle_unique"}),
}

RETIRED_COLUMNS: dict[str, frozenset[str]] = {
    "agents": frozenset({"product_role", "run_kind"}),
}
