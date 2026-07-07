import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { PiSwarmDependencies } from "../../../dependencies.ts";
import { registerReviewCommand } from "../command.ts";

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

function createFakeDeps(): PiSwarmDependencies {
	return {
		basecampExtensionRoot: "/basecamp",
		registerCatalogProvider() {
			/* no-op */
		},
		resolveModelAlias() {
			return undefined;
		},
		hasInvokedSkill() {
			return false;
		},
		getWorkspaceState() {
			return null;
		},
		formatTaskProgressSummary() {
			return null;
		},
		renderCompactTaskProgressLines() {
			return [];
		},
		formatTitle(title: string, tag: string) {
			return `${title} [${tag}]`;
		},
		shortSessionId(sessionId: string) {
			return sessionId.slice(0, 8);
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
});
