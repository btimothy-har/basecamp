import { describe, expect, test } from "bun:test";
import { join, resolve } from "node:path";
import { repositoryRelativePath } from "../paths.ts";

describe("review finding paths", () => {
	test("normalizes paths against the supplied repository root", () => {
		const root = resolve("repository");
		expect(repositoryRelativePath(join(root, "pi", "extension.ts"), root)).toBe("pi/extension.ts");
	});

	test("preserves relative and out-of-repository paths", () => {
		const root = resolve("repository");
		expect(repositoryRelativePath("omp/review/tool.ts", root)).toBe("omp/review/tool.ts");
		expect(repositoryRelativePath(resolve("other", "file.ts"), root)).toBe(resolve("other", "file.ts"));
	});

	test("uses platform separators when checking repository boundaries", () => {
		const root = resolve("volume", "repository");
		expect(repositoryRelativePath(join(root, "omp", "extension.ts"), root)).toBe("omp/extension.ts");
	});

	test("preserves absolute paths when no repository root exists", () => {
		expect(repositoryRelativePath(resolve("repository", "omp", "review", "tool.ts"), null)).toBe(
			resolve("repository", "omp", "review", "tool.ts"),
		);
	});
});
