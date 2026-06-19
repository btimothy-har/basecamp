---
name: agents
description: "Use the synchronous `agent` tool to delegate bounded work to subagents and then integrate the returned results in the parent session."
---

# Agents

Delegate bounded work through the synchronous `agent` tool and keep subagents as support for parent-agent reasoning.

## Delegation guidance

Use `agent` when a task is better done by a focused helper than by one long direct pass:
- **scout** for investigation, dependency tracing, codebase reconnaissance, or pattern discovery
- **devils-advocate** for risk-oriented critique of assumptions and planned approaches
- **worker** for self-contained implementation with clear scope and acceptance criteria
- **specialists** for narrow reviews (docs, security, tests, SQL, data, etc.) when available
- **ad-hoc** when no named specialization fits

## Choosing an agent

Default to the narrowest suitable choice:
1. pick a named **read-only** agent (`scout`, `devils-advocate`, specialists) for discovery and analysis
2. use **worker** only when mutation is required and boundaries are explicit
3. use ad-hoc for one-off, one-task questions

## Write a strong brief

A subagent receives no conversation history. Include:
- a concrete objective and expected output
- precise file/module targets and any constraints
- required decisions already made
- explicit acceptance criteria and done definition

## Calling `agent`

Use one of:
- `agent({ agent: "scout", task: "..." })`
- `agent({ task: "..." })` for ad-hoc

The synchronous call returns the subagent output in the same turn; plan and proceed with that result before continuing.

## Parallel restrictions

Multiple `agent` calls can run in parallel only when they are independent **named read-only** agents. Keep `worker` and ad-hoc runs exclusive and do not overlap with any other active agent run.

## Integration

After results return, the parent agent remains responsible for:
- validating evidence and assumptions
- deciding trade-offs and final direction
- integrating or applying code changes
- communicating any follow-up boundaries to the user

Treat delegated output as useful input, not source of authority.