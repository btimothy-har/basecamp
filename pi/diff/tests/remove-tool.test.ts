import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerRemoveTool } from "#diff/remove-tool.ts";
import { annotationId, sidecarPath, writeSidecar } from "#diff/sidecar.ts";

interface RegisteredTool {
	name: string;
	description: string;
	execute(toolCallId: string, params: { key: string }): Promise<{ content: { type: string; text: string }[] }>;
}

interface MockPi {
	tools: Map<string, RegisteredTool>;
	registerTool(tool: RegisteredTool): void;
}

function createMockPi(): MockPi {
	const tools = new Map<string, RegisteredTool>();
	return {
		tools,
		registerTool(tool: RegisteredTool) {
			tools.set(tool.name, tool);
		},
	};
}

function toolFor(t: TestContext, worktree: string): RegisteredTool {
	const originalDepth = process.env.BASECAMP_AGENT_DEPTH;
	const originalWorktree = process.env.BASECAMP_WORKTREE_DIR;
	const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "diff-rm-"));
	const originalScratch = process.env.BASECAMP_SCRATCH_DIR;
	process.env.BASECAMP_AGENT_DEPTH = "0";
	process.env.BASECAMP_WORKTREE_DIR = worktree;
	process.env.BASECAMP_SCRATCH_DIR = scratch;
	t.after(() => {
		fs.rmSync(scratch, { recursive: true, force: true });
		for (const [key, value] of [
			["BASECAMP_AGENT_DEPTH", originalDepth],
			["BASECAMP_WORKTREE_DIR", originalWorktree],
			["BASECAMP_SCRATCH_DIR", originalScratch],
		] as const) {
			if (value === undefined) delete process.env[key];
			else process.env[key] = value;
		}
	});
	const pi = createMockPi();
	registerRemoveTool(pi as unknown as ExtensionAPI);
	const tool = pi.tools.get("remove_annotation");
	assert.ok(tool);
	return tool;
}

describe("remove_annotation registration", () => {
	it("registers in a primary session and not in a subagent", (t) => {
		const original = process.env.BASECAMP_AGENT_DEPTH;
		t.after(() => {
			if (original === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = original;
		});

		process.env.BASECAMP_AGENT_DEPTH = "0";
		const primary = createMockPi();
		registerRemoveTool(primary as unknown as ExtensionAPI);
		assert.ok(primary.tools.has("remove_annotation"));
		assert.match(primary.tools.get("remove_annotation")?.description ?? "", /later edit invalidated/);

		process.env.BASECAMP_AGENT_DEPTH = "1";
		const subagent = createMockPi();
		registerRemoveTool(subagent as unknown as ExtensionAPI);
		assert.equal(subagent.tools.size, 0);
	});
});

describe("remove_annotation execution", () => {
	it("withdraws an annotation by its key", async (t) => {
		const tool = toolFor(t, "/wt/rm-tool");
		writeSidecar("/wt/rm-tool", "abc1234", "S.", [
			{
				path: "a.ts",
				annotations: [
					{ newRange: [1, 5], summary: "keep" },
					{ newRange: [6, 7], summary: "drop" },
				],
			},
		]);

		const result = await tool.execute("call-1", { key: annotationId("a.ts", [6, 7], "drop") });

		assert.match(result.content[0]?.text ?? "", /Withdrew annotation/);
		const written = JSON.parse(fs.readFileSync(sidecarPath("/wt/rm-tool"), "utf8")) as {
			files: { annotations: { summary: string }[] }[];
		};
		assert.deepEqual(
			written.files[0]?.annotations.map((a) => a.summary),
			["keep"],
		);
	});

	it("errors loudly on an unknown key rather than silently succeeding", async (t) => {
		const tool = toolFor(t, "/wt/rm-unknown");
		writeSidecar("/wt/rm-unknown", "abc1234", "S.", [
			{ path: "a.ts", annotations: [{ newRange: [1, 1], summary: "x" }] },
		]);

		await assert.rejects(() => tool.execute("call-1", { key: "deadbeefdead" }), /not found/);
	});

	it("reports a missing sidecar as nothing to withdraw", async (t) => {
		const tool = toolFor(t, "/wt/rm-empty");

		await assert.rejects(() => tool.execute("call-1", { key: "deadbeefdead" }), /no annotations recorded/);
	});
});
