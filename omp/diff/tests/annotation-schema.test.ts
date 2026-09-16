import { describe, expect, test } from "bun:test";
import { type as arktype } from "@oh-my-pi/omptype";
import {
	type AnnotateDiffInput,
	createAnnotateDiffParameters,
	createRemoveAnnotationParameters,
} from "../annotation-tools.ts";

const annotateParameters = createAnnotateDiffParameters(arktype);
const removeParameters = createRemoveAnnotationParameters(arktype);

function input(overrides: Partial<AnnotateDiffInput["annotations"][number]> = {}): AnnotateDiffInput {
	return {
		annotations: [
			{
				path: "src/a.ts",
				line_start: 2,
				line_end: 4,
				summary: "watch this",
				...overrides,
			},
		],
	};
}

function acceptsAnnotate(value: unknown): boolean {
	return !(annotateParameters(value) instanceof arktype.errors);
}

function acceptsRemove(value: unknown): boolean {
	return !(removeParameters(value) instanceof arktype.errors);
}

describe("diff annotation tool schemas", () => {
	test("annotate_diff accepts valid payloads with optional rationale", () => {
		expect(acceptsAnnotate(input())).toBe(true);
		expect(acceptsAnnotate(input({ rationale: "why" }))).toBe(true);
	});

	test("annotate_diff rejects unknown fields at both levels", () => {
		expect(acceptsAnnotate({ ...input(), bogus: true })).toBe(false);
		expect(acceptsAnnotate({ annotations: [{ ...input().annotations[0], id: "forged" }] })).toBe(false);
	});

	test("annotate_diff rejects invalid ranges and empty payloads", () => {
		expect(acceptsAnnotate(input({ line_start: 0 }))).toBe(false);
		expect(acceptsAnnotate(input({ line_start: 4, line_end: 2 }))).toBe(false);
		expect(acceptsAnnotate({ annotations: [] })).toBe(false);
		expect(acceptsAnnotate(input({ summary: "" }))).toBe(false);
	});

	test("remove_annotation accepts ids and rejects malformed payloads", () => {
		expect(acceptsRemove({ ids: ["aaaaaaaaaaaa"] })).toBe(true);
		expect(acceptsRemove({ ids: [] })).toBe(false);
		expect(acceptsRemove({ ids: ["a", 2] })).toBe(false);
		expect(acceptsRemove({ ids: ["a"], extra: true })).toBe(false);
	});
});
