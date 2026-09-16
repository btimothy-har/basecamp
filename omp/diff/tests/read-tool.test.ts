import { describe, expect, test } from "bun:test";
import { type as arktype } from "@oh-my-pi/omptype";
import type { ExtensionAPI, ExtensionContext, ExtensionMode, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { createDiffLoader, type DiffSnapshot, type LoadDiff, type LoadDiffOptions } from "../loader.ts";
import registerReadDiffTool, { createReadDiffParameters, type ReadDiffDetails } from "../read-tool.ts";

function snapshot(overrides: Partial<DiffSnapshot> = {}): DiffSnapshot {
	return {
		repositoryRoot: "/repo",
		repository: "acme/widgets",
		defaultBranch: "main",
		baseRevision: "0123456789abcdef",
		headRevision: "fedcba9876543210",
		patch: "diff --git a/f.ts b/f.ts\n--- a/f.ts\n+++ b/f.ts\n@@ -1 +1 @@\n-a\n+b\n",
		files: [{ path: "f.ts", newRanges: [{ start: 1, end: 1 }], newLines: new Map([[1, "b"]]) }],
		...overrides,
	};
}

function harness(load: LoadDiff, mode: ExtensionMode = "tui") {
	let definition: ToolDefinition | undefined;
	const api = {
		arktype,
		registerTool(tool: ToolDefinition): void {
			definition = tool;
		},
	} as unknown as ExtensionAPI;
	registerReadDiffTool(api, load);
	if (!definition) throw new Error("read_diff was not registered");
	const tool = definition;
	const ctx = { cwd: "/repo", mode } as unknown as ExtensionContext;
	return {
		definition: tool,
		async execute(input: { paths?: string[] } = {}, signal?: AbortSignal) {
			return tool.execute("call-1", input, signal, undefined, ctx);
		},
	};
}

function stubLoad(result: DiffSnapshot | Error) {
	const calls: Array<{ cwd: string; options?: LoadDiffOptions }> = [];
	const load: LoadDiff = async (cwd, options) => {
		calls.push({ cwd, options });
		if (result instanceof Error) throw result;
		return result;
	};
	return { load, calls };
}

describe("read_diff registration", () => {
	test("registers as an essential read tool", () => {
		const { definition } = harness(stubLoad(snapshot()).load);
		expect(definition.name).toBe("read_diff");
		expect(definition.approval).toBe("read");
		expect(definition.loadMode).toBe("essential");
		expect(definition.strict).toBe(true);
	});

	test("executes in every agent mode", async () => {
		for (const mode of ["tui", "rpc", "json", "print"] as const) {
			const { execute } = harness(stubLoad(snapshot()).load, mode);
			const result = await execute();
			expect(result.details).toMatchObject({ empty: false });
		}
	});
});

describe("read_diff execution", () => {
	test("returns the exact loader patch", async () => {
		const patch = "diff --git a/f.ts b/f.ts\n--- a/f.ts\n+++ b/f.ts\n@@ -1 +1 @@\n-a\n+b\n";
		const { execute } = harness(stubLoad(snapshot({ patch })).load);

		const result = await execute();

		expect(result.content).toEqual([{ type: "text", text: patch }]);
		expect(result.details).toMatchObject({
			repository: "acme/widgets",
			defaultBranch: "main",
			baseRevision: "0123456789abcdef",
			headRevision: "fedcba9876543210",
			fileCount: 1,
			empty: false,
		});
	});

	test("returns an explicit empty result when the diff is empty", async () => {
		const { execute } = harness(stubLoad(snapshot({ patch: "", files: [] })).load);

		const result = await execute();

		const text = result.content.find((part) => part.type === "text")?.text ?? "";
		expect(text).toContain("No changes");
		expect(text).toContain("0123456789abcdef");
		expect(result.details).toMatchObject({ empty: true, fileCount: 0 });
	});

	test("returns loader warnings separately from the frozen patch", async () => {
		const warning = 'Untracked directory "vendor/" was omitted; embedded repositories are not expanded.';
		const { execute } = harness(stubLoad(snapshot({ warnings: [warning] })).load);

		const result = await execute();

		expect(result.content.at(-1)).toEqual({ type: "text", text: `Diff warnings:\n- ${warning}` });
		expect((result.details as ReadDiffDetails).warnings).toEqual([warning]);
	});

	test("loads the diff for the session cwd and forwards paths and the signal", async () => {
		const { load, calls } = stubLoad(snapshot());
		const { execute } = harness(load);
		const controller = new AbortController();

		await execute({ paths: ["src/a.ts"] }, controller.signal);

		expect(calls.length).toBe(1);
		expect(calls[0]?.cwd).toBe("/repo");
		expect(calls[0]?.options?.paths).toEqual(["src/a.ts"]);
		expect(calls[0]?.options?.signal).toBe(controller.signal);
	});

	test("propagates loader failures", async () => {
		const { execute } = harness(stubLoad(new Error("not a repository")).load);
		await expect(execute()).rejects.toThrow("not a repository");
	});

	test("rejects path traversal through the real loader", async () => {
		const load = createDiffLoader({
			openRepository: () => {
				throw new Error("must not be reached");
			},
			env: {},
		});
		const { execute } = harness(load);

		await expect(execute({ paths: ["../outside.ts"] })).rejects.toThrow("escapes the repository");
	});
});

describe("read_diff parameters", () => {
	const parameters = createReadDiffParameters(arktype);
	const accepts = (value: unknown) => !(parameters(value) instanceof arktype.errors);

	test("accepts omitted and populated path filters", () => {
		expect(accepts({})).toBe(true);
		expect(accepts({ paths: ["src/a.ts", "docs"] })).toBe(true);
	});

	test("rejects unknown fields and empty paths", () => {
		expect(accepts({ bogus: true })).toBe(false);
		expect(accepts({ paths: [""] })).toBe(false);
		expect(accepts({ paths: "src/a.ts" })).toBe(false);
	});
});
