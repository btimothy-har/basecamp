import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { type ReviewCommandDeps, registerReviewCommand } from "../command.ts";

type CommandOptions = Parameters<ExtensionAPI["registerCommand"]>[1];

interface RegisteredCommandCall {
	name: string;
	spec: CommandOptions;
}

function createFakePi(): ExtensionAPI {
	const commands: RegisteredCommandCall[] = [];
	return {
		commands,
		registerCommand(name: string, spec: CommandOptions) {
			commands.push({ name, spec });
		},
	} as unknown as ExtensionAPI;
}

function createFakeDeps(): ReviewCommandDeps {
	return {
		basecampExtensionRoot: "/basecamp",
		resolveModelAlias() {
			return undefined;
		},
		getWorkspaceState() {
			return null;
		},
	};
}

describe("registerReviewCommand", () => {
	it("registers the code-review command with a non-empty description", () => {
		const pi = createFakePi();
		registerReviewCommand(pi, createFakeDeps());

		const commands = (pi as unknown as { commands: RegisteredCommandCall[] }).commands;
		assert.equal(commands.length, 1);
		assert.equal(commands[0]?.name, "code-review");
		assert.equal(typeof commands[0]?.spec.description, "string");
		assert.notEqual(commands[0]?.spec.description?.trim(), "");
	});

	it("notifies and returns before daemon or dispatch setup when run in a subagent", async (t) => {
		const originalDepth = process.env.BASECAMP_AGENT_DEPTH;
		t.after(() => {
			if (originalDepth === undefined) {
				delete process.env.BASECAMP_AGENT_DEPTH;
				return;
			}
			process.env.BASECAMP_AGENT_DEPTH = originalDepth;
		});

		let sendUserMessageCalled = false;
		let getSessionNameCalled = false;
		const commands: RegisteredCommandCall[] = [];
		const pi = {
			commands,
			registerCommand(name: string, spec: CommandOptions) {
				commands.push({ name, spec });
			},
			sendUserMessage() {
				sendUserMessageCalled = true;
				throw new Error("sendUserMessage should not be called");
			},
			getSessionName() {
				getSessionNameCalled = true;
				throw new Error("getSessionName should not be called");
			},
		} as unknown as ExtensionAPI & { commands: RegisteredCommandCall[] };
		const notifications: Array<{ message: string; level: string }> = [];
		const ctx = {
			cwd: "/repo",
			signal: undefined,
			model: null,
			sessionManager: {
				getSessionId() {
					throw new Error("sessionManager should not be called");
				},
			},
			ui: {
				notify(message: string, level: string) {
					notifications.push({ message, level });
				},
			},
		} as unknown as ExtensionCommandContext;

		registerReviewCommand(pi, createFakeDeps());
		process.env.BASECAMP_AGENT_DEPTH = "1";
		await pi.commands[0]?.spec.handler("", ctx);

		assert.deepEqual(notifications, [
			{
				message: "Code review is disabled in subagents; run /code-review from the top-level session.",
				level: "warning",
			},
		]);
		assert.equal(sendUserMessageCalled, false);
		assert.equal(getSessionNameCalled, false);
	});
});
