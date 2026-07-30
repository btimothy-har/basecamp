import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import registerBashReviewer, { isReviewerDisabled } from "#bash-reviewer/index.ts";
import { isReviewerPaused, setReviewerPaused } from "#bash-reviewer/state.ts";

type ToolCallEvent = { toolName: string; input: { command?: string } };
type Handler = (event: ToolCallEvent, ctx: unknown) => Promise<unknown>;

interface FakeCommand {
	name: string;
	description: string;
	handler: (args: string, ctx: unknown) => Promise<void>;
	getArgumentCompletions?: (prefix: string) => unknown;
}

function fakePi(sandboxedFlag: boolean): {
	events: string[];
	handlers: Map<string, Handler>;
	commands: FakeCommand[];
	pi: ExtensionAPI;
} {
	const events: string[] = [];
	const handlers = new Map<string, Handler>();
	const commands: FakeCommand[] = [];
	const pi = {
		on: (event: string, handler: Handler) => {
			events.push(event);
			handlers.set(event, handler);
		},
		registerCommand: (name: string, options: Omit<FakeCommand, "name">) => {
			commands.push({ name, ...options });
		},
		getFlag: (name: string) => (name === "unsafe-edit-sandboxed" ? sandboxedFlag : undefined),
		appendEntry: () => {},
	} as unknown as ExtensionAPI;
	return { events, handlers, commands, pi };
}

function fakeCtx(): unknown {
	return {
		hasUI: false,
		signal: undefined,
		sessionManager: { getEntries: () => [] },
		ui: {},
	};
}

function fakeUICtx(notifications: string[]): unknown {
	return {
		hasUI: true,
		signal: undefined,
		sessionManager: { getEntries: () => [] },
		ui: {
			notify: (msg: string) => notifications.push(msg),
			setStatus: () => {},
			theme: { fg: (_c: string, t: string) => t },
		},
	};
}

function setEnv(name: string, value: string | undefined): void {
	if (value === undefined) delete process.env[name];
	else process.env[name] = value;
}

describe("bash-reviewer disable predicate", () => {
	it("disables only when both env signals and the launch flag agree", () => {
		for (const envReviewer of ["off", undefined]) {
			for (const envSandbox of ["1", undefined]) {
				for (const flag of [true, false]) {
					const expected = envReviewer === "off" && envSandbox === "1" && flag;
					assert.equal(
						isReviewerDisabled(envReviewer, envSandbox, flag),
						expected,
						`(${envReviewer}, ${envSandbox}, ${flag})`,
					);
				}
			}
		}
	});

	it("rejects other off-switch and sandbox values", () => {
		assert.equal(isReviewerDisabled("on", "1", true), false);
		assert.equal(isReviewerDisabled("", "1", true), false);
		assert.equal(isReviewerDisabled("off", "true", true), false);
	});
});

describe("bash-reviewer per-call gate", () => {
	let priorReviewer: string | undefined;
	let priorSandbox: string | undefined;
	let priorPaused: string | undefined;

	beforeEach(() => {
		priorReviewer = process.env.BASECAMP_BASH_REVIEWER;
		priorSandbox = process.env.BASECAMP_EXTERNAL_SANDBOX;
		priorPaused = process.env.BASECAMP_BASH_REVIEWER_PAUSED;
		setEnv("BASECAMP_BASH_REVIEWER_PAUSED", undefined);
	});

	afterEach(() => {
		setEnv("BASECAMP_BASH_REVIEWER", priorReviewer);
		setEnv("BASECAMP_EXTERNAL_SANDBOX", priorSandbox);
		setEnv("BASECAMP_BASH_REVIEWER_PAUSED", priorPaused);
	});

	// The hook must always register: an opted-out session still carries the
	// reviewer, and /reload cannot change whether the gate exists.
	it("always registers the tool_call hook, even with the full disable env set", () => {
		setEnv("BASECAMP_BASH_REVIEWER", "off");
		setEnv("BASECAMP_EXTERNAL_SANDBOX", "1");

		const disabled = fakePi(true);
		registerBashReviewer(disabled.pi);
		assert.ok(disabled.handlers.has("tool_call"));

		const enabled = fakePi(false);
		registerBashReviewer(enabled.pi);
		assert.ok(enabled.handlers.has("tool_call"));
	});

	it("registers session lifecycle hooks and /bash-guard command", () => {
		const { handlers, commands, pi } = fakePi(false);
		registerBashReviewer(pi);
		assert.ok(handlers.has("session_start"));
		assert.ok(handlers.has("session_shutdown"));
		assert.ok(commands.some((c) => c.name === "bash-guard"));
	});

	it("skips review only when env and launch flag all agree", async () => {
		setEnv("BASECAMP_BASH_REVIEWER", "off");
		setEnv("BASECAMP_EXTERNAL_SANDBOX", "1");

		// Not fast-path safe, and this context resolves no reviewer model, so the enabled path lands
		// in the no-UI failsafe and blocks — observable without wiring up a model.
		const command = "bq query 'select 1'";

		const disabled = fakePi(true);
		registerBashReviewer(disabled.pi);
		const disabledResult = await disabled.handlers.get("tool_call")?.(
			{ toolName: "bash", input: { command } },
			fakeCtx(),
		);
		assert.equal(disabledResult, undefined);

		const enabled = fakePi(false);
		registerBashReviewer(enabled.pi);
		const enabledResult = await enabled.handlers.get("tool_call")?.(
			{ toolName: "bash", input: { command } },
			fakeCtx(),
		);
		assert.equal((enabledResult as { block?: boolean }).block, true);
	});

	it("keeps reviewing when only the env pair is set without the flag", async () => {
		setEnv("BASECAMP_BASH_REVIEWER", "off");
		setEnv("BASECAMP_EXTERNAL_SANDBOX", undefined);

		const { handlers, pi } = fakePi(true);
		registerBashReviewer(pi);
		const result = await handlers.get("tool_call")?.(
			{ toolName: "bash", input: { command: "bq query 'select 1'" } },
			fakeCtx(),
		);
		assert.equal((result as { block?: boolean }).block, true);
	});

	it("skips the LLM gate when paused but fast path still runs", async () => {
		// A trivially-safe command returns undefined (allowed) regardless of pause.
		const { handlers, pi } = fakePi(false);
		registerBashReviewer(pi);

		setReviewerPaused(true);
		assert.equal(isReviewerPaused(), true);

		// Fast-path safe command — allowed even when paused (no model call).
		const safeResult = await handlers.get("tool_call")?.({ toolName: "bash", input: { command: "ls -la" } }, fakeCtx());
		assert.equal(safeResult, undefined);

		// Non-trivial command — gate skipped when paused, so allowed (undefined).
		const gatedResult = await handlers.get("tool_call")?.(
			{ toolName: "bash", input: { command: "bq query 'select 1'" } },
			fakeCtx(),
		);
		assert.equal(gatedResult, undefined);

		// Resume — non-trivial command now hits the no-UI failsafe and blocks.
		setReviewerPaused(false);
		const resumedResult = await handlers.get("tool_call")?.(
			{ toolName: "bash", input: { command: "bq query 'select 1'" } },
			fakeCtx(),
		);
		assert.equal((resumedResult as { block?: boolean }).block, true);
	});
});

describe("/bash-guard command", () => {
	let priorPaused: string | undefined;

	beforeEach(() => {
		priorPaused = process.env.BASECAMP_BASH_REVIEWER_PAUSED;
		setEnv("BASECAMP_BASH_REVIEWER_PAUSED", undefined);
	});

	afterEach(() => {
		setEnv("BASECAMP_BASH_REVIEWER_PAUSED", priorPaused);
	});

	it("toggles pause on with no args, off with 'off', on with 'on'", async () => {
		const { commands, pi } = fakePi(false);
		registerBashReviewer(pi);
		const cmd = commands.find((c) => c.name === "bash-guard")!;
		assert.ok(cmd);

		const notifications: string[] = [];

		// Start unpaused → toggle to paused.
		assert.equal(isReviewerPaused(), false);
		await cmd.handler("", fakeUICtx(notifications));
		assert.equal(isReviewerPaused(), true);

		// Explicit "on" → unpause.
		await cmd.handler("on", fakeUICtx(notifications));
		assert.equal(isReviewerPaused(), false);

		// Explicit "off" → pause.
		await cmd.handler("off", fakeUICtx(notifications));
		assert.equal(isReviewerPaused(), true);

		// Toggle back to unpaused.
		await cmd.handler("", fakeUICtx(notifications));
		assert.equal(isReviewerPaused(), false);
	});

	it("provides on/off argument completions", () => {
		const { commands, pi } = fakePi(false);
		registerBashReviewer(pi);
		const cmd = commands.find((c) => c.name === "bash-guard")!;
		assert.ok(cmd.getArgumentCompletions);

		const all = cmd.getArgumentCompletions!("") as { value: string }[];
		assert.deepEqual(
			all.map((i) => i.value),
			["on", "off"],
		);

		const filtered = cmd.getArgumentCompletions!("of") as { value: string }[];
		assert.deepEqual(
			filtered.map((i) => i.value),
			["off"],
		);
	});
});
