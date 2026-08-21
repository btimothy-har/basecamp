import type { ExtensionAPI, ExtensionCommandContext, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { isSubagent } from "#core/host/env.ts";
import { completeLens } from "./completion.ts";
import { projectVisibleSession } from "./projection.ts";
import { buildLensRequest, calculateLensBudget } from "./prompt.ts";
import { LensRuntime } from "./runtime.ts";
import { LENS_OPERATIONS, LensError, type LensOperation } from "./types.ts";

export interface SessionLensDeps {
	project: typeof projectVisibleSession;
	complete: typeof completeLens;
}

const DEFAULT_DEPS: SessionLensDeps = {
	project: projectVisibleSession,
	complete: completeLens,
};

const DESCRIPTIONS: Record<LensOperation, string> = {
	explain: "Explain the current session in accessible language using the configured explainer model",
	tldr: "Summarize the current session using the configured explainer model",
	rephrase: "Restate the current session as cohesive human-readable prose using the configured explainer model",
};

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

async function runLens(
	operation: LensOperation,
	guidance: string,
	ctx: ExtensionCommandContext,
	runtime: LensRuntime,
	deps: SessionLensDeps,
): Promise<void> {
	if (ctx.mode !== "tui") {
		ctx.ui.notify(`/${operation} requires Pi's interactive TUI.`, "warning");
		return;
	}

	const run = runtime.begin(ctx);
	const viewport = runtime.showLoading(ctx, run.token, operation);
	try {
		await ctx.waitForIdle();
		if (!runtime.isCurrent(run.token)) return;

		const conversation = deps.project(ctx.sessionManager.getEntries(), ctx.sessionManager.getLeafId());
		if (!conversation) throw new LensError("empty", "There is no session content to transform yet.");

		const budget = calculateLensBudget(operation, viewport);
		const request = buildLensRequest(operation, guidance, conversation, budget);
		const result = await deps.complete(ctx, request, run.signal);
		runtime.showResult(ctx, run.token, operation, result);
	} catch (error) {
		if (!runtime.isCurrent(run.token) || (error instanceof LensError && error.code === "aborted")) return;
		runtime.dismiss(ctx);
		ctx.ui.notify(`/${operation}: ${errorMessage(error)}`, "error");
	}
}

function dismissOnInput(runtime: LensRuntime, ctx: ExtensionContext): void {
	if (runtime.hasActive()) runtime.dismiss(ctx);
}

export function registerSessionLensCommands(
	pi: ExtensionAPI,
	runtime: LensRuntime = new LensRuntime(),
	deps: SessionLensDeps = DEFAULT_DEPS,
): void {
	if (isSubagent()) return;

	for (const operation of LENS_OPERATIONS) {
		pi.registerCommand(operation, {
			description: DESCRIPTIONS[operation],
			handler: (guidance, ctx) => runLens(operation, guidance, ctx, runtime, deps),
		});
	}

	pi.registerCommand("dismiss", {
		description: "Dismiss the active session-lens card or generation",
		handler: async (_args, ctx) => {
			const wasActive = runtime.hasActive();
			runtime.dismiss(ctx);
			if (!wasActive && ctx.mode === "tui") ctx.ui.notify("No session-lens card is active.", "info");
		},
	});

	pi.on("input", (_event, ctx) => {
		dismissOnInput(runtime, ctx);
	});
	pi.on("session_start", (_event, ctx) => {
		runtime.dismiss(ctx);
	});
	pi.on("session_shutdown", (_event, ctx) => {
		runtime.dismiss(ctx);
	});
}
