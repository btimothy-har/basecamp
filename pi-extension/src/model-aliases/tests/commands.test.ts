import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionCommandContext, RegisteredCommand } from "@earendil-works/pi-coding-agent";
import { registerModelAliasCommands } from "../commands.ts";

function createPi() {
	const commands = new Map<string, Omit<RegisteredCommand, "name" | "sourceInfo">>();
	const pi = {
		registerCommand(name: string, options: Omit<RegisteredCommand, "name" | "sourceInfo">) {
			commands.set(name, options);
		},
	} as unknown as ExtensionAPI;

	return { pi, commands };
}

describe("registerModelAliasCommands", () => {
	it("registers the model-aliases command", () => {
		const { pi, commands } = createPi();

		registerModelAliasCommands(pi);

		const command = commands.get("model-aliases");
		assert.ok(command);
		assert.equal(command.description, "Manage native model aliases");
		assert.equal(typeof command.handler, "function");
	});

	it("notifies and exits when UI is unavailable", async () => {
		const { pi, commands } = createPi();
		const notifications: Array<{ message: string; level?: string }> = [];
		registerModelAliasCommands(pi);

		const command = commands.get("model-aliases");
		assert.ok(command);

		await command.handler("", {
			hasUI: false,
			ui: {
				notify(message: string, level?: string) {
					notifications.push({ message, level });
				},
			},
		} as unknown as ExtensionCommandContext);

		assert.deepEqual(notifications, [
			{ message: "The /model-aliases command requires an interactive UI.", level: "info" },
		]);
	});
});
