# session-lens

Primary-TUI conversation lenses for inspecting an active session without steering its working agent. `/explain`, `/tldr`, and `/rephrase` send a filtered view of the current conversation branch to a separately configured model, then show its response outside the primary transcript.

## User surface

| Command | Lens |
|---|---|
| `/explain [guidance]` | Explain the conversation, its decisions, or a requested point of confusion. |
| `/tldr [guidance]` | Produce a concise account of what matters in the conversation. |
| `/rephrase [guidance]` | Restate the conversation for a requested audience, tone, or level of detail. |
| `/dismiss` | Close the displayed lens card. |

Without guidance, each model-backed command covers the whole current active conversation branch. Guidance steers the lens—for example, toward one decision or a less technical audience—but is not a range selector and does not change the default source.

The commands exist only in a primary session with an interactive TUI. They are not registered for subagents, background workers, or headless sessions.

## Context boundary

A lens sees the conversation as the user can meaningfully resume it, not a raw session dump:

- only the current active branch is read directly; an abandoned path appears only when Pi already carries it into the active context as a branch summary;
- compacted history is represented by its retained compaction summary, followed by the visible entries that remain after the compaction boundary;
- visible user and assistant text plus context-visible bash activity is included;
- tool calls are summarized and each tool result is bounded, preserving useful operational evidence without allowing one result payload to dominate the request;
- hidden thinking, hidden custom messages, and image content are excluded.

This boundary is both a privacy choice and a fidelity trade-off. A lens can explain what was said and the bounded evidence of what was done, but it cannot recover pre-compaction detail, inspect visual-only evidence, or infer hidden reasoning.

## Model boundary

Session lenses require a model alias named `explainer`, configured through `/model-aliases`. The alias is resolved independently for every invocation so configuration and provider authentication changes take effect without borrowing the primary session model. There is deliberately no fallback to that primary model: the separate alias keeps cost, capability, and data-routing choices explicit.

The resolved model receives a purpose-built lens prompt, the filtered context, the selected operation, and any optional guidance. It receives no Basecamp working-agent prompt and no tools. The call uses Pi's model-registry completion surface so native and configured providers keep their normal authentication and request handling without the deprecated compatibility API. A lens is therefore a single interpretive model call, not a second agent that can inspect files, continue the task, or act on the session.

## Presentation and lifecycle

A successful response becomes the one active lens card: a bordered, one-screen view pinned above the editor. The editor remains active while the card is visible, so reading a lens never takes over the interaction surface. A later successful lens replaces the card.

The card is ephemeral. The next normal user message closes it as the primary conversation resumes, and `/dismiss` closes it explicitly. Lens prompts and results are never appended to the primary transcript or fed back to the working model. This avoids self-referential context growth, at the cost of the result not being durable session history; users must copy anything they want to retain.

## Failure policy

Failures stay on the secondary surface and never switch models or modify the primary transcript:

- a missing or unresolvable `explainer` alias reports that it must be configured or corrected with `/model-aliases`;
- no eligible context after filtering reports that there is nothing to process and makes no provider call;
- missing authentication reports that the configured provider needs credentials;
- input that cannot fit the explainer model's context window is rejected rather than silently changing scope or falling back to another model;
- provider and completion failures are reported as UI errors and do not install a new lens card.

In every case the primary editor and conversation remain available. This fail-without-fallback posture favors an explicit absence of a lens over a plausible-looking result produced by the wrong model or from an unmarked partial context.
