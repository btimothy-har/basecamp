import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Value } from "@sinclair/typebox/value";
import { AnnotateChangesetParams, registerAnnotateTool } from "#diff/annotate-tool.ts";

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
	exec(command: string, args: string[]): Promise<{ code: number; stdout: string; stderr: string; killed: boolean }>;
}

const STUB_BASE = "43e3afd68b290430804ef6d7cc0fba60336dcd98";

function createMockPi(): MockPi {
	const tools = new Map<string, RegisteredTool>();
	return {
		tools,
		registerTool(tool: RegisteredTool) {
			tools.set(tool.name, tool);
		},
		// The tool stamps the sidecar with the review base, so it resolves git.
		async exec(_command: string, args: string[]) {
			const stdout = args.join(" ").includes("merge-base") ? STUB_BASE : "origin/main";
			return { code: 0, stdout, stderr: "", killed: false };
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

describe("annotate_changeset parameters", () => {
	const valid = {
		summary: "S.",
		files: [{ path: "a.ts", annotations: [{ startLine: 4, endLine: 9, summary: "x" }] }],
	};

	it("accepts a well-formed changeset", () => {
		assert.equal(Value.Check(AnnotateChangesetParams, valid), true);
	});

	it("rejects line numbers hunk refuses to load", () => {
		// hunk aborts before registering a session on a 0-based or negative line,
		// and the sidecar is reused, so /diff would stay broken until it is deleted.
		for (const startLine of [0, -1]) {
			const params = { ...valid, files: [{ path: "a.ts", annotations: [{ startLine, endLine: 9, summary: "x" }] }] };
			assert.equal(Value.Check(AnnotateChangesetParams, params), false, `startLine ${startLine} must be rejected`);
		}
		const zeroEnd = { ...valid, files: [{ path: "a.ts", annotations: [{ startLine: 1, endLine: 0, summary: "x" }] }] };
		assert.equal(Value.Check(AnnotateChangesetParams, zeroEnd), false);
	});

	it("rejects an empty summary and unknown properties", () => {
		assert.equal(Value.Check(AnnotateChangesetParams, { ...valid, summary: "" }), false);
		assert.equal(Value.Check(AnnotateChangesetParams, { ...valid, extra: 1 }), false);
	});

	it("no longer accepts the tuple form", () => {
		const tuple = { ...valid, files: [{ path: "a.ts", annotations: [{ newRange: [1, 2], summary: "x" }] }] };
		assert.equal(Value.Check(AnnotateChangesetParams, tuple), false);
	});
});

describe("annotate_changeset execution", () => {
	function toolFor(t: TestContext, worktree?: string) {
		preserveDepth(t);
		process.env.BASECAMP_AGENT_DEPTH = "0";
		preserveScratch(t);
		if (worktree) preserveWorktreeDir(t, worktree);
		const pi = createMockPi();
		registerAnnotateTool(pi as unknown as ExtensionAPI);
		const tool = pi.tools.get("annotate_changeset");
		assert.ok(tool);
		return tool;
	}

	it("writes the sidecar and returns a confirmation with counts", async (t) => {
		const tool = toolFor(t, "/wt/exec");

		const result = await tool.execute("call-1", {
			summary: "Changeset summary.",
			files: [
				{
					path: "pi/diff/sidecar.ts",
					annotations: [
						{ startLine: 1, endLine: 10, summary: "writer" },
						{ startLine: 12, endLine: 20, summary: "path", rationale: "hash-based" },
					],
				},
				{ path: "pi/diff/annotate-tool.ts", annotations: [{ startLine: 1, endLine: 5, summary: "tool" }] },
			],
		});

		const text = result.content[0]?.text ?? "";
		assert.match(text, /3 annotations/);
		assert.match(text, /2 files/);

		const details = result.details as { sidecarPath: string; files: number; annotations: number };
		assert.equal(details.annotations, 3);

		const written = JSON.parse(fs.readFileSync(details.sidecarPath, "utf8")) as {
			version: number;
			basecampBase: string;
			files: { annotations: { newRange: [number, number] }[] }[];
		};
		assert.equal(written.version, 1);
		assert.equal(written.basecampBase, STUB_BASE, "the sidecar records the base it was anchored against");
		// The wire format hunk reads is a tuple, whatever shape the tool accepts.
		assert.deepEqual(written.files[0]?.annotations[0]?.newRange, [1, 10]);
	});

	it("refuses an inverted range instead of writing a sidecar hunk cannot load", async (t) => {
		const tool = toolFor(t, "/wt/inverted");

		await assert.rejects(
			() =>
				tool.execute("call-1", {
					summary: "S.",
					files: [{ path: "a.ts", annotations: [{ startLine: 20, endLine: 10, summary: "x" }] }],
				}),
			/endLine must not precede startLine/,
		);
	});

	it("falls back to process.cwd() when BASECAMP_WORKTREE_DIR is unset", async (t) => {
		const original = process.env.BASECAMP_WORKTREE_DIR;
		delete process.env.BASECAMP_WORKTREE_DIR;
		t.after(() => {
			if (original === undefined) delete process.env.BASECAMP_WORKTREE_DIR;
			else process.env.BASECAMP_WORKTREE_DIR = original;
		});
		const tool = toolFor(t);

		const result = await tool.execute("call-1", {
			summary: "S.",
			files: [{ path: "a.ts", annotations: [{ startLine: 1, endLine: 1, summary: "x" }] }],
		});

		assert.ok(fs.existsSync((result.details as { sidecarPath: string }).sidecarPath));
	});
});
