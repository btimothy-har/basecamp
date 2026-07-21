import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext, ToolCallEvent } from "@earendil-works/pi-coding-agent";
import { registerBashReviewer } from "../index.ts";

interface EmittedEvent {
	channel: string;
	data: unknown;
}

type ToolCallHandler = (event: ToolCallEvent, ctx: ExtensionContext) => Promise<unknown>;

class FakePi {
	readonly emitted: EmittedEvent[] = [];
	readonly events = {
		emit: (channel: string, data: unknown) => {
			this.emitted.push({ channel, data });
		},
		on: () => () => {},
	};
	private toolCallHandler: ToolCallHandler | null = null;

	on(eventName: string, handler: ToolCallHandler): void {
		if (eventName === "tool_call") this.toolCallHandler = handler;
	}

	appendEntry(): void {}

	getToolCallHandler(): ToolCallHandler {
		assert.ok(this.toolCallHandler, "bash reviewer tool_call handler should be registered");
		return this.toolCallHandler;
	}
}

const blockedStart: EmittedEvent = {
	channel: "herdr:blocked",
	data: { active: true, label: "Waiting for command approval" },
};
const blockedEnd: EmittedEvent = { channel: "herdr:blocked", data: { active: false } };

function register(): { pi: FakePi; handler: ToolCallHandler } {
	const pi = new FakePi();
	registerBashReviewer(pi as unknown as ExtensionAPI);
	return { pi, handler: pi.getToolCallHandler() };
}

function bashEvent(): ToolCallEvent {
	return { toolName: "bash", input: { command: "git commit -m 'test'" } } as ToolCallEvent;
}

function context(confirm: () => Promise<boolean>, hasUI = true): ExtensionContext {
	return {
		hasUI,
		signal: new AbortController().signal,
		model: null,
		modelRegistry: {
			getAll: () => [],
			find: () => undefined,
		},
		sessionManager: { getEntries: () => [] },
		ui: {
			confirm,
			notify() {},
		},
	} as unknown as ExtensionContext;
}

describe("bash reviewer Herdr state", () => {
	it("marks Herdr blocked only while command approval is open", async () => {
		const { pi, handler } = register();
		const lifecycle: string[] = [];
		pi.events.emit = (channel, data) => {
			const active = (data as { active: boolean }).active;
			lifecycle.push(`${channel}:${active}`);
			pi.emitted.push({ channel, data });
		};
		const ctx = context(async () => {
			lifecycle.push("confirm");
			return true;
		});

		const outcome = await handler(bashEvent(), ctx);

		assert.equal(outcome, undefined);
		assert.deepEqual(lifecycle, ["herdr:blocked:true", "confirm", "herdr:blocked:false"]);
		assert.deepEqual(pi.emitted, [blockedStart, blockedEnd]);
	});

	it("clears blocked state when command approval is declined", async () => {
		const { pi, handler } = register();

		const outcome = await handler(
			bashEvent(),
			context(async () => false),
		);

		assert.deepEqual(outcome, {
			block: true,
			reason: "Command blocked: reviewer unavailable (reviewer model unavailable) and user declined.",
		});
		assert.deepEqual(pi.emitted, [blockedStart, blockedEnd]);
	});

	it("clears blocked state when command approval rejects", async () => {
		const { pi, handler } = register();
		const ctx = context(async () => {
			throw new Error("approval failed");
		});

		const outcome = await handler(bashEvent(), ctx);

		assert.deepEqual(outcome, {
			block: true,
			reason: "Command blocked: reviewer unavailable (reviewer model unavailable) and user declined.",
		});
		assert.deepEqual(pi.emitted, [blockedStart, blockedEnd]);
	});

	it("does not report blocked state when command approval has no UI", async () => {
		const { pi, handler } = register();
		const ctx = context(async () => {
			throw new Error("confirm should not be called");
		}, false);

		const outcome = await handler(bashEvent(), ctx);

		assert.equal((outcome as { block?: boolean } | undefined)?.block, true);
		assert.deepEqual(pi.emitted, []);
	});
});
