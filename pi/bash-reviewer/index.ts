import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isToolCallEventType } from "@earendil-works/pi-coding-agent";
import { getBasecampEnv, isSubagent } from "#core/host/env.ts";
import { recentUserMessages } from "#core/session/user-context.ts";
import { withHerdrBlocked } from "#core/ui/herdr.ts";
import { resolveGateModel, runGate } from "./llm.ts";
import { type ReviewDeps, reviewBashCommand } from "./review.ts";

/**
 * Off only when two genuinely independent channels agree: the environment
 * (`BASECAMP_BASH_REVIEWER=off` plus `BASECAMP_EXTERNAL_SANDBOX=1`) and the
 * `--unsafe-edit-sandboxed` launch flag — the same flag session.ts pairs with
 * the sandbox env var. Both env vars live in `process.env`, which a repo
 * `.env` or a stray export can populate, so env alone must never strip the
 * gate; argv cannot be forged that way. The eval adapter (harbor) passes the
 * flag on the pi command line alongside the env vars.
 *
 * The Terminal-Bench profile is the only opt-out consumer. There the reviewer
 * has no `fast` alias to resolve — the trial container never receives
 * basecamp's config — so every gate verdict would reach the no-UI failsafe and
 * hard-block a command the shipped reviewer would have judged on its merits.
 * Measuring that teaches nothing about the agent, so the profile opts out and
 * says so in its metadata.
 */
export function isReviewerDisabled(
	envReviewer: string | undefined,
	envSandbox: string | undefined,
	sandboxedFlag: boolean,
): boolean {
	return envReviewer === "off" && envSandbox === "1" && sandboxedFlag;
}

export function registerBashReviewer(pi: ExtensionAPI): void {
	pi.on("tool_call", async (event, ctx) => {
		if (!isToolCallEventType("bash", event)) return undefined;

		const command = event.input.command ?? "";
		if (command === "") return undefined;

		// Checked per call, not at registration: the hook is always present, and
		// /reload cannot silently change whether the gate exists.
		if (
			isReviewerDisabled(
				getBasecampEnv("BASECAMP_BASH_REVIEWER"),
				getBasecampEnv("BASECAMP_EXTERNAL_SANDBOX"),
				pi.getFlag("unsafe-edit-sandboxed") === true,
			)
		) {
			return undefined;
		}

		const deps: ReviewDeps = {
			resolveModel: () => resolveGateModel(ctx),
			recentMessages: () => recentUserMessages(ctx.sessionManager.getEntries()),
			runGate: (args) => runGate(args),
			confirm: (title, body) =>
				withHerdrBlocked(pi, "Waiting for command approval", () => ctx.ui.confirm(title, body, { signal: ctx.signal })),
			hasUI: ctx.hasUI,
			isSubagent: isSubagent(),
			signal: ctx.signal,
			audit: (entry) => pi.appendEntry("bash-reviewer", entry),
			notify: (message, type) => {
				if (ctx.hasUI) ctx.ui.notify(message, type);
			},
		};

		return await reviewBashCommand(command, deps);
	});
}

export default registerBashReviewer;
