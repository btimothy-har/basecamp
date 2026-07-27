import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerAnnotateTool } from "#diff/annotate-tool.ts";

interface RegisteredTool {
	name: string;
	description: string;
	parameters: object;
	execute(
		toolCallId: string,
		params: unknown,
		signal?: AbortSignal,
		onUpdate?: unknown,
		ctx?: unknown,
	): Promise<{
		content: { type: string; text: string }[];
		details?: unknown;
	}>;
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

function preserveDepth(t: TestContext): void {
	const original = process.env.BASECAMP_AGENT_DEPTH;
	t.after(() => {
		if (original === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
		else process.env.BASECAMP_AGENT_DEPTH = original;
	});
}

function preserveScratch(t: TestContext): string {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "diff-tool-"));
	const original = process.env.BASECAMP_SCRATCH_DIR;
	t.after(() => {
		fs.rmSync(dir, { recursive: true, force: true });
		if (original === undefined) delete process.env.BASECAMP_SCRATCH_DIR;
		else process.env.BASECAMP_SCRATCH_DIR = original;
	});
	process.env.BASECAMP_SCRATCH_DIR = dir;
	return dir;
}

function preserveWorktreeDir(t: TestContext, worktree: string): void {
	const original = process.env.BASECAMP_WORKTREE_DIR;
	t.after(() => {
		if (original === undefined) delete process.env.BASECAMP_WORKTREE_DIR;
		else process.env.BASECAMP_WORKTREE_DIR = original;
	});
	process.env.BASECAMP_WORKTREE_DIR = worktree;
}

describe("annotate_changeset registration", () => {
	it("registers the tool in a primary session", (t) => {
		preserveDepth(t);
		process.env.BASECAMP_AGENT_DEPTH = "0";
		const pi = createMockPi();

		registerAnnotateTool(pi as unknown as ExtensionAPI);

		assert.ok(pi.tools.has("annotate_changeset"));
		const tool = pi.tools.get("annotate_changeset");
		assert.ok(tool);
		assert.match(tool.description, /once, when the work is complete/);
	});

	it("does not register the tool in a subagent process", (t) => {
		preserveDepth(t);
		process.env.BASECAMP_AGENT_DEPTH = "1";
		const pi = createMockPi();

		registerAnnotateTool(pi as unknown as ExtensionAPI);

		assert.equal(pi.tools.size, 0);
	});
});

describe("annotate_changeset execution", () => {
	it("writes the sidecar and returns a confirmation with counts", async (t) => {
		preserveDepth(t);
		process.env.BASECAMP_AGENT_DEPTH = "0";
		preserveScratch(t);
		preserveWorktreeDir(t, "/wt/exec");

		const pi = createMockPi();
		registerAnnotateTool(pi as unknown as ExtensionAPI);
		const tool = pi.tools.get("annotate_changeset");
		assert.ok(tool);

		const result = await tool.execute("call-1", {
			summary: "Changeset summary.",
			files: [
				{
					path: "pi/diff/sidecar.ts",
					annotations: [
						{ newRange: [1, 10], summary: "writer" },
						{ newRange: [12, 20], summary: "path", rationale: "hash-based" },
					],
				},
				{ path: "pi/diff/annotate-tool.ts", annotations: [{ newRange: [1, 5], summary: "tool" }] },
			],
		});

		assert.equal(result.content.length, 1);
		assert.equal(result.content[0]?.type, "text");
		const text = result.content[0]?.text ?? "";
		assert.match(text, /3 annotations/);
		assert.match(text, /2 files/);
		assert.match(text, /\/diff/);

		const details = result.details as { sidecarPath: string; files: number; annotations: number };
		assert.equal(details.files, 2);
		assert.equal(details.annotations, 3);
		assert.ok(fs.existsSync(details.sidecarPath));

		const written = JSON.parse(fs.readFileSync(details.sidecarPath, "utf8")) as { version: number; summary: string };
		assert.equal(written.version, 1);
		assert.equal(written.summary, "Changeset summary.");
	});

	it("falls back to process.cwd() when BASECAMP_WORKTREE_DIR is unset", async (t) => {
		preserveDepth(t);
		process.env.BASECAMP_AGENT_DEPTH = "0";
		preserveScratch(t);
		const original = process.env.BASECAMP_WORKTREE_DIR;
		delete process.env.BASECAMP_WORKTREE_DIR;
		t.after(() => {
			if (original === undefined) delete process.env.BASECAMP_WORKTREE_DIR;
			else process.env.BASECAMP_WORKTREE_DIR = original;
		});

		const pi = createMockPi();
		registerAnnotateTool(pi as unknown as ExtensionAPI);
		const tool = pi.tools.get("annotate_changeset");
		assert.ok(tool);

		const result = await tool.execute("call-1", {
			summary: "S.",
			files: [{ path: "a.ts", annotations: [{ newRange: [1, 1], summary: "x" }] }],
		});

		const details = result.details as { sidecarPath: string };
		assert.ok(fs.existsSync(details.sidecarPath));
	});
});
