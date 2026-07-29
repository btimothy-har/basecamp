import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import registerBashReviewer, { isReviewerDisabled } from "#bash-reviewer/index.ts";

type ToolCallEvent = { toolName: string; input: { command?: string } };
type Handler = (event: ToolCallEvent, ctx: unknown) => Promise<unknown>;

function fakePi(sandboxedFlag: boolean): { events: string[]; handlers: Handler[]; pi: ExtensionAPI } {
	const events: string[] = [];
	const handlers: Handler[] = [];
	const pi = {
		on: (event: string, handler: Handler) => {
			events.push(event);
			handlers.push(handler);
		},
		getFlag: (name: string) => (name === "unsafe-edit-sandboxed" ? sandboxedFlag : undefined),
		appendEntry: () => {},
	} as unknown as ExtensionAPI;
	return { events, handlers, pi };
}

function fakeCtx(): unknown {
	return {
		hasUI: false,
		signal: undefined,
		sessionManager: { getEntries: () => [] },
		ui: {},
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

	beforeEach(() => {
		priorReviewer = process.env.BASECAMP_BASH_REVIEWER;
		priorSandbox = process.env.BASECAMP_EXTERNAL_SANDBOX;
	});

	afterEach(() => {
		setEnv("BASECAMP_BASH_REVIEWER", priorReviewer);
		setEnv("BASECAMP_EXTERNAL_SANDBOX", priorSandbox);
	});

	// The hook must always register: an opted-out session still carries the
	// reviewer, and /reload cannot change whether the gate exists.
	it("always registers the tool_call hook, even with the full disable env set", () => {
		setEnv("BASECAMP_BASH_REVIEWER", "off");
		setEnv("BASECAMP_EXTERNAL_SANDBOX", "1");

		const disabled = fakePi(true);
		registerBashReviewer(disabled.pi);
		assert.deepEqual(disabled.events, ["tool_call"]);

		const enabled = fakePi(false);
		registerBashReviewer(enabled.pi);
		assert.deepEqual(enabled.events, ["tool_call"]);
	});

	it("skips review only when env and launch flag all agree", async () => {
		setEnv("BASECAMP_BASH_REVIEWER", "off");
		setEnv("BASECAMP_EXTERNAL_SANDBOX", "1");

		// Not fast-path safe, and this context resolves no reviewer model, so the enabled path lands
		// in the no-UI failsafe and blocks — observable without wiring up a model.
		const command = "bq query 'select 1'";

		const disabled = fakePi(true);
		registerBashReviewer(disabled.pi);
		const disabledResult = await disabled.handlers[0]?.({ toolName: "bash", input: { command } }, fakeCtx());
		assert.equal(disabledResult, undefined);

		const enabled = fakePi(false);
		registerBashReviewer(enabled.pi);
		const enabledResult = await enabled.handlers[0]?.({ toolName: "bash", input: { command } }, fakeCtx());
		assert.equal((enabledResult as { block?: boolean }).block, true);
	});

	it("keeps reviewing when only the env pair is set without the flag", async () => {
		setEnv("BASECAMP_BASH_REVIEWER", "off");
		setEnv("BASECAMP_EXTERNAL_SANDBOX", undefined);

		const { handlers, pi } = fakePi(true);
		registerBashReviewer(pi);
		const result = await handlers[0]?.({ toolName: "bash", input: { command: "bq query 'select 1'" } }, fakeCtx());
		assert.equal((result as { block?: boolean }).block, true);
	});
});
