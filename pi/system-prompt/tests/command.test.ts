import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionCommandContext, RegisteredCommand } from "@earendil-works/pi-coding-agent";
import { registerSystemPromptCommand } from "#system-prompt/command.ts";
import { registerPrompt } from "#system-prompt/prompt.ts";
import type { SystemPromptPreview } from "#system-prompt/viewer.ts";
import { useAgentDepth } from "./helpers.ts";

type Command = Omit<RegisteredCommand, "name" | "sourceInfo">;

type Notice = { message: string; level?: string };

function commandHarness(t: Parameters<typeof useAgentDepth>[0], depth = 0) {
	useAgentDepth(t, depth);
	const commands = new Map<string, Command>();
	const pi = {
		registerCommand(name: string, command: Command) {
			commands.set(name, command);
		},
	} as unknown as ExtensionAPI;
	return { pi, commands };
}

function commandContext(
	options: { mode?: ExtensionCommandContext["mode"]; modelId?: string; customPrompt?: string; notices?: Notice[] } = {},
): ExtensionCommandContext {
	const notices = options.notices ?? [];
	return {
		mode: options.mode ?? "tui",
		model: options.modelId ? { id: options.modelId } : undefined,
		getSystemPromptOptions: () => ({ cwd: "/repo", customPrompt: options.customPrompt }),
		ui: {
			notify(message: string, level?: string) {
				notices.push({ message, level });
			},
		},
	} as unknown as ExtensionCommandContext;
}

describe("/system-prompt", () => {
	it("registers only in primary sessions", (t) => {
		const primary = commandHarness(t);
		registerSystemPromptCommand(primary.pi);
		assert.equal(
			primary.commands.get("system-prompt")?.description,
			"Preview Basecamp's freshly compiled system prompt",
		);
	});

	it("is absent from subagent sessions", (t) => {
		const subagent = commandHarness(t, 1);
		registerSystemPromptCommand(subagent.pi);
		assert.equal(subagent.commands.has("system-prompt"), false);
	});

	it("fresh-compiles on every invocation and labels custom-prompt bypass", async (t) => {
		const { pi, commands } = commandHarness(t);
		const previews: SystemPromptPreview[] = [];
		const modelIds: Array<string | undefined> = [];
		let compileCount = 0;
		registerSystemPromptCommand(pi, {
			compile: (_pi, modelId) => {
				modelIds.push(modelId);
				return `compiled-${++compileCount}`;
			},
			show: async (preview) => {
				previews.push(preview);
			},
		});
		const command = commands.get("system-prompt");
		assert.ok(command);

		await command.handler("", commandContext({ modelId: "first" }));
		await command.handler("  ", commandContext({ modelId: "second", customPrompt: "custom" }));

		assert.deepEqual(modelIds, ["first", "second"]);
		assert.deepEqual(previews, [
			{ prompt: "compiled-1", inactive: false },
			{ prompt: "compiled-2", inactive: true },
		]);
	});

	it("rejects arguments before compiling", async (t) => {
		const { pi, commands } = commandHarness(t);
		const notices: Notice[] = [];
		let compiled = false;
		registerSystemPromptCommand(pi, {
			compile: () => {
				compiled = true;
				return "prompt";
			},
		});

		await commands.get("system-prompt")!.handler("active", commandContext({ notices }));

		assert.equal(compiled, false);
		assert.deepEqual(notices, [{ message: "/system-prompt does not accept arguments.", level: "error" }]);
	});

	it("requires TUI mode before compiling", async (t) => {
		const { pi, commands } = commandHarness(t);
		const notices: Notice[] = [];
		let compiled = false;
		registerSystemPromptCommand(pi, {
			compile: () => {
				compiled = true;
				return "prompt";
			},
		});

		await commands.get("system-prompt")!.handler("", commandContext({ mode: "rpc", notices }));

		assert.equal(compiled, false);
		assert.deepEqual(notices, [{ message: "/system-prompt requires the interactive terminal UI.", level: "info" }]);
	});

	it("reports compilation and viewer failures separately", async (t) => {
		const compileNotices: Notice[] = [];
		const compileHarness = commandHarness(t);
		registerSystemPromptCommand(compileHarness.pi, {
			compile: () => {
				throw new Error("compile failed");
			},
		});
		await compileHarness.commands.get("system-prompt")!.handler("", commandContext({ notices: compileNotices }));
		assert.deepEqual(compileNotices, [{ message: "Could not compile system prompt: compile failed", level: "error" }]);

		const viewerNotices: Notice[] = [];
		const viewerHarness = commandHarness(t);
		registerSystemPromptCommand(viewerHarness.pi, {
			compile: () => "prompt",
			show: async () => {
				throw new Error("viewer failed");
			},
		});
		await viewerHarness.commands.get("system-prompt")!.handler("", commandContext({ notices: viewerNotices }));
		assert.deepEqual(viewerNotices, [{ message: "Could not show system prompt: viewer failed", level: "error" }]);
	});
});

describe("prompt hook", () => {
	it("uses the shared compiler only when Pi supplies its default prompt", async () => {
		let handler: ((event: { systemPrompt: string }, ctx: { model?: { id: string } }) => unknown) | undefined;
		const pi = {
			on(event: string, next: typeof handler) {
				if (event === "before_agent_start") handler = next;
			},
		} as unknown as ExtensionAPI;
		const calls: Array<string | undefined> = [];
		registerPrompt(pi, (_pi, modelId) => {
			calls.push(modelId);
			return "compiled";
		});
		assert.ok(handler);

		const replacement = await handler(
			{ systemPrompt: "You are an expert coding assistant with tools." },
			{ model: { id: "model" } },
		);
		const bypassed = await handler({ systemPrompt: "Custom prompt" }, {});

		assert.deepEqual(replacement, { systemPrompt: "compiled" });
		assert.equal(bypassed, undefined);
		assert.deepEqual(calls, ["model"]);
	});
});
