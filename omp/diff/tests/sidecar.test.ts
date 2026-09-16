import { afterEach, describe, expect, test } from "bun:test";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { DiffAnnotation } from "../annotations.ts";
import {
	AGENT_CONTEXT_VERSION,
	PRIVATE_DIR_MODE,
	PRIVATE_FILE_MODE,
	projectAgentContext,
	writeAgentContext,
	writeReviewPatch,
} from "../sidecar.ts";

const tempRoots: string[] = [];
const originalScratch = process.env.BASECAMP_SCRATCH_DIR;

afterEach(() => {
	let root = tempRoots.pop();
	while (root !== undefined) {
		fs.rmSync(root, { recursive: true, force: true });
		root = tempRoots.pop();
	}
	if (originalScratch === undefined) delete process.env.BASECAMP_SCRATCH_DIR;
	else process.env.BASECAMP_SCRATCH_DIR = originalScratch;
});

function tempDir(): string {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), "omp-diff-sidecar-"));
	tempRoots.push(root);
	return root;
}

function annotation(overrides: Partial<DiffAnnotation> = {}): DiffAnnotation {
	return {
		id: "ann-1",
		repository: "repo",
		path: "src/app.ts",
		newRange: { start: 12, end: 18 },
		anchorHash: "abc123",
		summary: "check the timeout here",
		...overrides,
	};
}

describe("projectAgentContext", () => {
	test("emits hunk's agent-context shape with inclusive tuple ranges", () => {
		const projection = projectAgentContext(
			[
				annotation({ rationale: "a 4s poll can outlive the pane" }),
				annotation({ id: "ann-2", path: "src/other.ts", newRange: { start: 3, end: 3 }, summary: "rename me" }),
			],
			"Two concerns",
		);
		expect(projection).toEqual({
			version: AGENT_CONTEXT_VERSION,
			summary: "Two concerns",
			files: [
				{
					path: "src/app.ts",
					annotations: [
						{ newRange: [12, 18], summary: "check the timeout here", rationale: "a 4s poll can outlive the pane" },
					],
				},
				{ path: "src/other.ts", annotations: [{ newRange: [3, 3], summary: "rename me" }] },
			],
		});
	});

	test("omits the rationale key entirely when there is none", () => {
		const projection = projectAgentContext([annotation()], "s");
		const serialized = JSON.stringify(projection);
		expect(serialized).not.toContain("rationale");
		expect(serialized).not.toContain("anchorHash");
		expect(serialized).not.toContain('"id"');
	});

	test("groups annotations for the same file in input order", () => {
		const projection = projectAgentContext(
			[
				annotation({ id: "ann-1", summary: "first" }),
				annotation({ id: "ann-2", path: "b.ts", summary: "other file" }),
				annotation({ id: "ann-3", summary: "second", newRange: { start: 40, end: 41 } }),
			],
			"s",
		);
		expect(projection.files.map((file) => file.path)).toEqual(["src/app.ts", "b.ts"]);
		expect(projection.files[0]?.annotations.map((a) => a.summary)).toEqual(["first", "second"]);
	});

	test("refuses an empty batch so the orchestrator launches without --agent-context", () => {
		expect(() => projectAgentContext([], "s")).toThrow("at least one annotation");
	});

	test("refuses to mix repositories into one hunk session", () => {
		expect(() => projectAgentContext([annotation(), annotation({ id: "ann-2", repository: "other" })], "s")).toThrow(
			"multiple repositories",
		);
	});

	test("refuses a reversed or non-integer range", () => {
		expect(() => projectAgentContext([annotation({ newRange: { start: 9, end: 4 } })], "s")).toThrow(
			/invalid newRange/,
		);
		expect(() => projectAgentContext([annotation({ newRange: { start: 1.5, end: 4 } })], "s")).toThrow(
			/invalid newRange/,
		);
	});

	test("refuses an empty path", () => {
		expect(() => projectAgentContext([annotation({ path: " " })], "s")).toThrow("empty path");
	});
});

describe("writeAgentContext", () => {
	test("writes the projection to a private file inside a private scratch dir", () => {
		const scratch = tempDir();
		process.env.BASECAMP_SCRATCH_DIR = scratch;
		const handle = writeAgentContext([annotation({ rationale: "why" })]);
		try {
			expect(handle.annotations).toBe(1);
			expect(path.dirname(handle.path)).toBe(path.join(scratch, "diff"));
			expect(fs.statSync(handle.path).mode & 0o777).toBe(PRIVATE_FILE_MODE);
			expect(fs.statSync(path.dirname(handle.path)).mode & 0o777).toBe(PRIVATE_DIR_MODE);
			expect(JSON.parse(fs.readFileSync(handle.path, "utf8"))).toEqual(
				projectAgentContext([annotation({ rationale: "why" })], "Agent annotations (1 recorded)"),
			);
		} finally {
			handle.cleanup();
		}
	});

	test("honors a caller-supplied summary", () => {
		process.env.BASECAMP_SCRATCH_DIR = tempDir();
		const handle = writeAgentContext([annotation()], { summary: "Review of the diff" });
		try {
			const written = JSON.parse(fs.readFileSync(handle.path, "utf8")) as { summary: string };
			expect(written.summary).toBe("Review of the diff");
		} finally {
			handle.cleanup();
		}
	});

	test("cleanup removes the file and is idempotent", () => {
		process.env.BASECAMP_SCRATCH_DIR = tempDir();
		const handle = writeAgentContext([annotation()]);
		expect(fs.existsSync(handle.path)).toBe(true);
		handle.cleanup();
		expect(fs.existsSync(handle.path)).toBe(false);
		expect(() => handle.cleanup()).not.toThrow();
	});

	test("never reuses a path across projections", () => {
		process.env.BASECAMP_SCRATCH_DIR = tempDir();
		const first = writeAgentContext([annotation()]);
		const second = writeAgentContext([annotation()]);
		try {
			expect(first.path).not.toBe(second.path);
		} finally {
			first.cleanup();
			second.cleanup();
		}
	});
});

describe("writeReviewPatch", () => {
	test("writes the exact frozen patch privately and removes it on cleanup", () => {
		const scratch = tempDir();
		process.env.BASECAMP_SCRATCH_DIR = scratch;
		const patch = "diff --git a/a.ts b/a.ts\n@@ -1 +1 @@\n-old\n+new\n";
		const handle = writeReviewPatch(patch);

		expect(path.extname(handle.path)).toBe(".patch");
		expect(fs.statSync(handle.path).mode & 0o777).toBe(PRIVATE_FILE_MODE);
		expect(fs.statSync(path.dirname(handle.path)).mode & 0o777).toBe(PRIVATE_DIR_MODE);
		expect(fs.readFileSync(handle.path, "utf8")).toBe(patch);

		handle.cleanup();
		expect(fs.existsSync(handle.path)).toBe(false);
		expect(() => handle.cleanup()).not.toThrow();
	});
});
