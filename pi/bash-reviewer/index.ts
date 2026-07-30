import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isToolCallEventType } from "@earendil-works/pi-coding-agent";
import type { AutocompleteItem } from "@earendil-works/pi-tui";
import { getBasecampEnv, isSubagent } from "#core/host/env.ts";
import { recentUserMessages } from "#core/session/user-context.ts";
import { withHerdrBlocked } from "#core/ui/herdr.ts";
import { resolveGateModel, runGate } from "./llm.ts";
import { type ReviewDeps, reviewBashCommand } from "./review.ts";
import { isReviewerPaused, onReviewerPauseChange, setReviewerPaused } from "./state.ts";
import { publishReviewerStatus } from "./status.ts";

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
			worktreeDir: getBasecampEnv("BASECAMP_WORKTREE_DIR") || undefined,
			runGate: (args) => runGate(args),
			confirm: (title, body) =>
				withHerdrBlocked(pi, "Waiting for command approval", () => ctx.ui.confirm(title, body, { signal: ctx.signal })),
			hasUI: ctx.hasUI,
			isSubagent: isSubagent(),
			paused: isReviewerPaused(),
			signal: ctx.signal,
			audit: (entry) => pi.appendEntry("bash-reviewer", entry),
			notify: (message, type) => {
				if (ctx.hasUI) ctx.ui.notify(message, type);
			},
		};

		return await reviewBashCommand(command, deps);
	});

	let unsubscribePause: (() => void) | null = null;
	pi.on("session_start", (_event, ctx) => {
		publishReviewerStatus(ctx, isReviewerPaused());
		unsubscribePause = onReviewerPauseChange((paused) => publishReviewerStatus(ctx, paused));
	});

	pi.on("session_shutdown", () => {
		unsubscribePause?.();
		unsubscribePause = null;
	});

	registerBashGuardCommand(pi);
}

/**
 * `/bash-guard` — temporary escape hatch for the bash reviewer.
 *
 * Toggles the LLM gate on/off mid-session. The fast path (`isTriviallySafe`)
 * always runs regardless — only the model gate is skipped when off. The pause
 * is process-scoped (survives `/reload`, not process restart) and propagates
 * to subagent spawns via `BASECAMP_BASH_REVIEWER_PAUSED`. Works in both primary
 * sessions and subagents.
 */
function registerBashGuardCommand(pi: ExtensionAPI): void {
	pi.registerCommand("bash-guard", {
		description: "Toggle the bash reviewer gate on or off (temporary session-level escape hatch)",
		getArgumentCompletions: (argumentPrefix: string): AutocompleteItem[] | null => {
			const prefix = argumentPrefix.toLowerCase();
			const items: AutocompleteItem[] = [
				{ value: "on", label: "on", description: "Resume gating bash commands" },
				{ value: "off", label: "off", description: "Skip the LLM gate (fast path still runs)" },
			];
			const filtered = items.filter((item) => item.value.startsWith(prefix));
			return filtered.length > 0 ? filtered : null;
		},
		handler: async (args, ctx) => {
			const arg = args?.trim().toLowerCase() ?? "";

			let next: boolean;
			if (arg === "on") next = false;
			else if (arg === "off") next = true;
			else next = !isReviewerPaused(); // toggle

			const result = setReviewerPaused(next);
			publishReviewerStatus(ctx, result);
			ctx.ui.notify(result ? "bash reviewer off — LLM gate skipped" : "bash reviewer on — gating active", "info");
		},
	});
}

export default registerBashReviewer;
