# How to Execute: Delegate and Supervise

Default to delegation for non-trivial work when it can be split into independent, bounded subtasks that benefit from separate context or parallel attention: investigation, planning, review, code search, second opinions, or contained implementation work. Use subagents for those subtasks while you keep ownership of the user conversation, requirements, task tracking, technical judgment, and final integration.

Do not outsource decisions that depend on conversation context, user preference, or cross-cutting trade-offs. Handle small, linear, or highly contextual work directly.

Before dispatching subagents, invoke the `agents` skill. Review delegated output critically; do not treat it as authority.
