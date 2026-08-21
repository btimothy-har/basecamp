import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type {
	ExtensionAPI,
	ExtensionCommandContext,
	ExtensionContext,
	RegisteredCommand,
	Theme,
} from "@earendil-works/pi-coding-agent";
import type { Component } from "@earendil-works/pi-tui";
import { registerSessionLensCommands, type SessionLensDeps } from "#session-lens/commands.ts";
import { LensRuntime } from "#session-lens/runtime.ts";
import { LensError, type LensResult, SESSION_LENS_WIDGET_ID } from "#session-lens/types.ts";

interface Registered {
	description?: string;
	handler: (args: string, ctx: ExtensionCommandContext) => Promise<void> | void;
}

class FakePi {
	commands = new Map<string, Registered>();
	handlers = new Map<string, Array<(event: unknown, ctx: ExtensionContext) => unknown>>();

	registerCommand(name: string, options: Omit<RegisteredCommand, "name" | "sourceInfo">): void {
		this.commands.set(name, options);
	}

	on(event: string, handler: (event: unknown, ctx: ExtensionContext) => unknown): void {
		this.handlers.set(event, [...(this.handlers.get(event) ?? []), handler]);
	}
}

const theme = {
	fg: (_color: string, text: string) => text,
	bold: (text: string) => text,
} as unknown as Theme;

interface ContextHarness {
	ctx: ExtensionCommandContext;
	notifications: Array<{ message: string; type?: string }>;
	widgets: Array<{ key: string; component?: Component }>;
	waits: number;
}

function context(mode: ExtensionContext["mode"] = "tui"): ContextHarness {
	const notifications: ContextHarness["notifications"] = [];
	const widgets: ContextHarness["widgets"] = [];
	const state = { waits: 0 };
	const ctx = {
		mode,
		hasUI: mode === "tui",
		waitForIdle: async () => {
			state.waits++;
		},
		sessionManager: {
			getEntries: () => [],
			getLeafId: () => null,
		},
		ui: {
			notify: (message: string, type?: string) => notifications.push({ message, type }),
			setWidget: (key: string, factory: ((tui: unknown, theme: Theme) => Component) | undefined) => {
				const component = factory ? factory({ terminal: { columns: 100, rows: 40 } }, theme) : undefined;
				widgets.push({ key, component });
			},
		},
	} as unknown as ExtensionCommandContext;
	return {
		ctx,
		notifications,
		widgets,
		get waits() {
			return state.waits;
		},
	};
}

function result(text: string): LensResult {
	return {
		text,
		model: "openai/explain-1",
		budget: { maxCardLines: 20, maxContentLines: 15, maxWords: 200, maxOutputTokens: 400 },
	};
}

function deps(complete: SessionLensDeps["complete"]): SessionLensDeps {
	return { project: () => "[User]: visible session", complete };
}

async function emit(pi: FakePi, event: string, ctx: ExtensionContext): Promise<void> {
	for (const handler of pi.handlers.get(event) ?? []) await handler({}, ctx);
}

function rendered(widget: ContextHarness["widgets"][number] | undefined): string {
	return widget?.component?.render(100).join("\n") ?? "";
}

describe("session lens commands", () => {
	it("registers the command family and lifecycle only in primary sessions", (t) => {
		const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		t.after(() => {
			if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
		});

		delete process.env.BASECAMP_AGENT_DEPTH;
		const primary = new FakePi();
		registerSessionLensCommands(primary as unknown as ExtensionAPI);
		assert.deepEqual([...primary.commands.keys()], ["explain", "tldr", "rephrase", "dismiss"]);
		assert.deepEqual([...primary.handlers.keys()], ["input", "session_start", "session_shutdown"]);

		process.env.BASECAMP_AGENT_DEPTH = "1";
		const child = new FakePi();
		registerSessionLensCommands(child as unknown as ExtensionAPI);
		assert.equal(child.commands.size, 0);
		assert.equal(child.handlers.size, 0);
	});

	it("waits for idle, applies guidance, and replaces loading with a pinned result", async () => {
		const pi = new FakePi();
		const h = context();
		let guidance: unknown;
		registerSessionLensCommands(
			pi as unknown as ExtensionAPI,
			new LensRuntime(),
			deps(async (_ctx, request) => {
				guidance = JSON.parse(String(request.context.messages[0]?.content)).guidance;
				return result("Readable result");
			}),
		);

		await pi.commands.get("explain")?.handler("Focus on the trade-off", h.ctx);

		assert.equal(h.waits, 1);
		assert.equal(guidance, "Focus on the trade-off");
		assert.equal(h.widgets.length, 2);
		assert.equal(h.widgets[0]?.key, SESSION_LENS_WIDGET_ID);
		assert.match(rendered(h.widgets.at(-1)), /Readable result/);
		assert.match(rendered(h.widgets.at(-1)), /\/dismiss · next message closes/);
		assert.equal(h.notifications.length, 0);
	});

	it("dismisses on normal input and through /dismiss without entering the transcript", async () => {
		const pi = new FakePi();
		const h = context();
		let signal: AbortSignal | undefined;
		registerSessionLensCommands(
			pi as unknown as ExtensionAPI,
			new LensRuntime(),
			deps(async (_ctx, _request, requestSignal) => {
				signal = requestSignal;
				return new Promise<LensResult>((_resolve, reject) => {
					requestSignal.addEventListener("abort", () => reject(new LensError("aborted", "cancelled")), { once: true });
				});
			}),
		);

		const first = pi.commands.get("tldr")?.handler("", h.ctx);
		await new Promise((resolve) => setImmediate(resolve));
		await emit(pi, "input", h.ctx);
		await first;
		assert.equal(signal?.aborted, true);
		assert.equal(h.widgets.at(-1)?.component, undefined);

		const second = pi.commands.get("tldr")?.handler("", h.ctx);
		await new Promise((resolve) => setImmediate(resolve));
		await pi.commands.get("dismiss")?.handler("", h.ctx);
		await second;
		assert.equal(h.widgets.at(-1)?.component, undefined);
	});

	it("prevents an aborted stale completion from replacing a newer result", async () => {
		const pi = new FakePi();
		const h = context();
		let resolveFirst: ((value: LensResult) => void) | undefined;
		let call = 0;
		registerSessionLensCommands(
			pi as unknown as ExtensionAPI,
			new LensRuntime(),
			deps(async () => {
				call++;
				if (call === 1) return new Promise<LensResult>((resolve) => (resolveFirst = resolve));
				return result("newest result");
			}),
		);

		const first = pi.commands.get("explain")?.handler("", h.ctx);
		await new Promise((resolve) => setImmediate(resolve));
		await pi.commands.get("rephrase")?.handler("", h.ctx);
		resolveFirst?.(result("stale result"));
		await first;

		const visibleWidgets = h.widgets.filter((widget) => widget.component);
		assert.match(rendered(visibleWidgets.at(-1)), /newest result/);
		assert.doesNotMatch(rendered(visibleWidgets.at(-1)), /stale result/);
	});

	it("rejects non-TUI and empty sessions without calling the model", async () => {
		let calls = 0;
		const nonTuiPi = new FakePi();
		const nonTui = context("print");
		registerSessionLensCommands(
			nonTuiPi as unknown as ExtensionAPI,
			new LensRuntime(),
			deps(async () => {
				calls++;
				return result("unused");
			}),
		);
		await nonTuiPi.commands.get("tldr")?.handler("", nonTui.ctx);
		assert.equal(calls, 0);
		assert.match(nonTui.notifications[0]?.message ?? "", /interactive TUI/);

		const emptyPi = new FakePi();
		const empty = context();
		registerSessionLensCommands(emptyPi as unknown as ExtensionAPI, new LensRuntime(), {
			project: () => "",
			complete: async () => result("unused"),
		});
		await emptyPi.commands.get("explain")?.handler("", empty.ctx);
		assert.equal(empty.widgets.at(-1)?.component, undefined);
		assert.match(empty.notifications[0]?.message ?? "", /no session content/i);
	});
});
