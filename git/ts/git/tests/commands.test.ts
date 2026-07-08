import assert from "node:assert/strict";
import test from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerCommands } from "../commands.ts";

test("registerCommands registers create-pr only", () => {
	const commands: string[] = [];
	const pi = {
		registerCommand: (name: string) => {
			commands.push(name);
		},
	} as unknown as ExtensionAPI;

	registerCommands(pi);

	const removedCommandName = ["code", "walkthrough"].join("-");

	assert.deepEqual(commands, ["create-pr"]);
	assert.equal(commands.includes(removedCommandName), false);
});
