import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { getAgentMode, setAgentMode } from "../../agent-mode/index.ts";
import type { DaemonConnection } from "../connection.ts";
import { registerHubConnection } from "../index.ts";
import type { OutboundFrame } from "../protocol/index.ts";
import { clearHubMetadataWiring, getHubConnectionState } from "../state.ts";

type EventHandler = (...args: unknown[]) => unknown;

class MockPi {
	readonly handlers = new Map<string, EventHandler[]>();
	private readonly sessionName: string;

	constructor(sessionName: string) {
		this.sessionName = sessionName;
	}

	on(event: string, handler: unknown): void {
		const handlers = this.handlers.get(event) ?? [];
		handlers.push(handler as EventHandler);
		this.handlers.set(event, handlers);
	}

	getSessionName(): string {
		return this.sessionName;
	}

	setSessionName(): void {}

	emit(event: string, ...args: unknown[]): unknown[] {
		return (this.handlers.get(event) ?? []).map((handler) => handler(...args));
	}
}

async function startSession(pi: MockPi, ctx: ExtensionContext): Promise<void> {
	pi.emit("session_start", {}, ctx);
	const connecting = getHubConnectionState().connecting;
	assert.ok(connecting);
	await connecting;
}

describe("hub metadata lifecycle", () => {
	it("replaces metadata subscriptions when reload reuses the connection", async () => {
		const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		const priorMode = getAgentMode();
		const state = getHubConnectionState();
		const sent: OutboundFrame[] = [];
		const closeHandlers = new Set<(code: number, reason: string) => void>();
		let closeCalls = 0;
		const connection = {
			send(frame: OutboundFrame) {
				sent.push(frame);
			},
			on() {
				return () => {};
			},
			onClose(handler: (code: number, reason: string) => void) {
				closeHandlers.add(handler);
				return () => closeHandlers.delete(handler);
			},
			close() {
				closeCalls++;
			},
		} as unknown as DaemonConnection;
		const ctx = { hasUI: false, model: { id: "test-model" } } as ExtensionContext;
		const firstLoad = new MockPi("First load");
		const reload = new MockPi("Reload");

		try {
			process.env.BASECAMP_AGENT_DEPTH = "0";
			clearHubMetadataWiring(state);
			state.connection = connection;
			state.connecting = null;

			registerHubConnection(firstLoad as unknown as ExtensionAPI);
			await startSession(firstLoad, ctx);
			assert.equal(closeHandlers.size, 1);

			registerHubConnection(reload as unknown as ExtensionAPI);
			await startSession(reload, ctx);
			assert.equal(closeHandlers.size, 1);

			const nextMode = priorMode === "analysis" ? "planning" : "analysis";
			const beforeModeChange = sent.length;
			setAgentMode(nextMode);
			assert.equal(sent.length, beforeModeChange + 1);

			await Promise.all(reload.emit("session_shutdown"));
			assert.equal(closeHandlers.size, 0);
			assert.equal(closeCalls, 1);
		} finally {
			clearHubMetadataWiring(state);
			state.connection = null;
			state.connecting = null;
			setAgentMode(priorMode);
			if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
		}
	});
});
