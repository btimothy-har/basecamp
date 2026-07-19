import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@earendil-works/pi-coding-agent";
import { resetCopilotLaunchForTesting, setCopilotLaunchReader } from "#core/agent-mode/copilot.ts";
import { getAgentMode, resetAgentMode } from "#core/agent-mode/index.ts";
import {
	getCurrentSessionState,
	initializeCurrentSessionState,
	resetCurrentSessionState,
} from "#core/session/state/index.ts";
import {
	defaultWorkstreamStartDeps,
	parseWorkstreamFlagValue,
	registerWorkstreamStartup,
	sessionHasPriorTurns,
} from "../start.ts";
import { FakeDaemonClient, makeCtx, makeDeps } from "./start-harness.ts";

class FakePi {
	readonly flags = new Map<string, { description: string; type: string }>();
	readonly userMessages: string[] = [];
	private readonly flagValues = new Map<string, unknown>();
	private sessionStart: ((event: SessionStartEvent, ctx: ExtensionContext) => Promise<void>) | null = null;

	registerFlag(name: string, flag: { description: string; type: string }): void {
		this.flags.set(name, flag);
	}

	getFlag(name: string): unknown {
		return this.flagValues.get(name);
	}

	setFlag(name: string, value: unknown): void {
		this.flagValues.set(name, value);
	}

	on(event: string, handler: (event: SessionStartEvent, ctx: ExtensionContext) => Promise<void>): void {
		if (event === "session_start") this.sessionStart = handler;
	}

	sendUserMessage(text: string): void {
		this.userMessages.push(text);
	}

	async emitSessionStart(ctx: ExtensionContext): Promise<void> {
		assert.ok(this.sessionStart, "session_start handler should be registered");
		await this.sessionStart({ type: "session_start", reason: "new" } as SessionStartEvent, ctx);
	}
}

describe("registerWorkstreamStartup", () => {
	afterEach(() => {
		resetCopilotLaunchForTesting();
	});

	it("registers a boolean startup flag", () => {
		const pi = new FakePi();
		const harness = makeDeps(new FakeDaemonClient());

		registerWorkstreamStartup(pi as unknown as ExtensionAPI, async () => null, harness.deps);

		assert.deepEqual(pi.flags.get("workstream"), {
			description:
				"Start the workstream for the current worktree. Bare --workstream infers the workstream from the copilot/<slug> worktree label; --workstream=<slug|id> resolves explicitly.",
			type: "boolean",
		});
	});

	it("copilot takes precedence over --workstream on session_start", async () => {
		const harness = makeDeps(new FakeDaemonClient());
		const pi = new FakePi();
		const { ctx, notices } = makeCtx();

		registerWorkstreamStartup(pi as unknown as ExtensionAPI, async () => null, harness.deps);
		pi.setFlag("workstream", true);
		setCopilotLaunchReader(() => true);
		await pi.emitSessionStart(ctx);

		assert.equal(harness.enterExploreModeCalls.length, 0);
		assert.equal(pi.userMessages.length, 0);
		assert.equal(notices.length, 1);
		assert.equal(notices[0]?.level, "warning");
		assert.match(notices[0]?.message ?? "", /copilot takes precedence/);
	});

	it("enters Explore mode and starts the workstream on session_start when the flag is present", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const pi = new FakePi();
		const { ctx } = makeCtx();

		registerWorkstreamStartup(pi as unknown as ExtensionAPI, async () => null, harness.deps);
		pi.setFlag("workstream", true);
		await pi.emitSessionStart(ctx);

		assert.equal(pi.userMessages.length, 1);
		assert.equal(harness.enterExploreModeCalls.length, 1);
		assert.equal(harness.enterExploreModeCalls[0]?.event.reason, "new");
		assert.equal(client.attachCalls.length, 1);
	});

	it("does not re-inject the brief or re-force mode when the session already has turns", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const pi = new FakePi();
		const { ctx } = makeCtx();

		registerWorkstreamStartup(pi as unknown as ExtensionAPI, async () => null, harness.deps);
		pi.setFlag("workstream", true);
		harness.setPriorTurns(true); // resume/reload/fork/compact — the brief is already in the thread
		await pi.emitSessionStart(ctx);

		assert.equal(pi.userMessages.length, 0);
		assert.equal(harness.enterExploreModeCalls.length, 0);
		assert.equal(client.attachCalls.length, 0);
	});

	it("does nothing on session_start when --workstream is absent", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const pi = new FakePi();
		const { ctx } = makeCtx();

		registerWorkstreamStartup(pi as unknown as ExtensionAPI, async () => null, harness.deps);
		await pi.emitSessionStart(ctx);

		assert.equal(pi.userMessages.length, 0);
		assert.equal(harness.enterExploreModeCalls.length, 0);
		assert.equal(client.attachCalls.length, 0);
	});
});

describe("defaultWorkstreamStartDeps enterExploreMode", () => {
	it("initializes session state and forces planning (Explore) mode", (t) => {
		const stateDir = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-workstream-mode-"));
		t.after(() => {
			resetCurrentSessionState();
			resetAgentMode();
			fs.rmSync(stateDir, { recursive: true, force: true });
		});

		const ctx = {
			hasUI: true,
			ui: { notify() {} },
			sessionManager: { getSessionId: () => "ws-mode-session", getSessionFile: () => null },
		} as unknown as ExtensionContext;
		initializeCurrentSessionState(ctx, stateDir);

		defaultWorkstreamStartDeps(async () => null).enterExploreMode(
			{ type: "session_start", reason: "new" } as SessionStartEvent,
			ctx,
		);

		assert.equal(getAgentMode(), "planning");
		assert.equal(getCurrentSessionState().agentMode, "planning");
	});
});

describe("sessionHasPriorTurns", () => {
	function ctxWithEntries(entries: unknown[]): ExtensionContext {
		return { sessionManager: { getEntries: () => entries } } as unknown as ExtensionContext;
	}

	it("is false for a fresh session with no entries", () => {
		assert.equal(sessionHasPriorTurns(ctxWithEntries([])), false);
	});

	it("is false when no sessionManager reader is available", () => {
		assert.equal(sessionHasPriorTurns({ sessionManager: {} } as unknown as ExtensionContext), false);
	});

	it("is true when a user or assistant message is present", () => {
		assert.equal(sessionHasPriorTurns(ctxWithEntries([{ type: "message", message: { role: "user" } }])), true);
		assert.equal(sessionHasPriorTurns(ctxWithEntries([{ type: "message", message: { role: "assistant" } }])), true);
	});

	it("ignores non-conversation entries (tool results, custom entries)", () => {
		assert.equal(
			sessionHasPriorTurns(
				ctxWithEntries([
					{ type: "message", message: { role: "toolResult" } },
					{ type: "custom", data: {} },
				]),
			),
			false,
		);
	});

	it("falls back to getBranch when getEntries is absent", () => {
		const ctx = {
			sessionManager: { getBranch: () => [{ type: "message", message: { role: "user" } }] },
		} as unknown as ExtensionContext;
		assert.equal(sessionHasPriorTurns(ctx), true);
	});
});

describe("parseWorkstreamFlagValue", () => {
	it("returns undefined for a bare --workstream", () => {
		assert.equal(parseWorkstreamFlagValue(["node", "pi", "--workstream"]), undefined);
	});

	it("recovers an explicit --workstream=<value>", () => {
		assert.equal(parseWorkstreamFlagValue(["node", "pi", "--workstream=my-slug"]), "my-slug");
		assert.equal(parseWorkstreamFlagValue(["--workstream=ws_abc123"]), "ws_abc123");
	});

	it("treats an empty or whitespace value as infer (undefined)", () => {
		assert.equal(parseWorkstreamFlagValue(["--workstream="]), undefined);
		assert.equal(parseWorkstreamFlagValue(["--workstream=   "]), undefined);
	});

	it("returns undefined when no --workstream arg is present", () => {
		assert.equal(parseWorkstreamFlagValue(["node", "pi", "--other=1"]), undefined);
	});
});
