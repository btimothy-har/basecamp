import { describe, expect, test } from "bun:test";
import { type as arktype } from "@oh-my-pi/omptype";
import { createReviewFindingsParameters, type ReviewFindingInput, type ReviewFindingsInput } from "../schema.ts";

const parameters = createReviewFindingsParameters(arktype);

function schemaAccepts(value: unknown): boolean {
	return !(parameters(value) instanceof arktype.errors);
}

function validFinding(overrides: Partial<ReviewFindingInput> = {}): ReviewFindingInput {
	return {
		title: "Unchecked redirect",
		body: "The redirect target is not validated, allowing open redirects.",
		recommendation: "Reject redirect targets outside the configured allowlist.",
		priority: 1,
		confidence: 0.8,
		file_path: "src/auth.ts",
		line_start: 12,
		line_end: 18,
		...overrides,
	};
}

function validInput(overrides: Partial<ReviewFindingsInput> = {}): ReviewFindingsInput {
	return {
		scope: "main...HEAD",
		overall_correctness: "incorrect",
		explanation: "The change introduces an open redirect.",
		recommendation: "Fix the redirect validation before merging.",
		confidence: 0.9,
		findings: [validFinding()],
		...overrides,
	};
}

describe("createReviewFindingsParameters", () => {
	test("accepts a valid payload", () => {
		expect(schemaAccepts(validInput())).toBe(true);
	});

	test("requires overall and finding recommendations", () => {
		const withoutOverall = { ...validInput() } as Record<string, unknown>;
		delete withoutOverall.recommendation;
		expect(schemaAccepts(withoutOverall)).toBe(false);

		const finding = { ...validFinding() } as Record<string, unknown>;
		delete finding.recommendation;
		expect(schemaAccepts(validInput({ findings: [finding as unknown as ReviewFindingInput] }))).toBe(false);
	});

	test("rejects unknown top-level fields", () => {
		expect(schemaAccepts({ ...validInput(), bogus: true })).toBe(false);
	});

	test("rejects unknown finding fields, including model-supplied id and feedback", () => {
		for (const extra of [{ id: "finding-1" }, { feedback: { comment: null } }, { bogus: 1 }]) {
			expect(schemaAccepts(validInput({ findings: [{ ...validFinding(), ...extra }] }))).toBe(false);
		}
	});

	test("rejects priorities outside the 0-3 integer range", () => {
		for (const priority of [-1, 4, 1.5, "high"]) {
			expect(schemaAccepts(validInput({ findings: [validFinding({ priority: priority as 0 })] }))).toBe(false);
		}
	});

	test("rejects confidence outside 0-1 on findings and on the review", () => {
		expect(schemaAccepts(validInput({ findings: [validFinding({ confidence: 1.5 })] }))).toBe(false);
		expect(schemaAccepts(validInput({ findings: [validFinding({ confidence: -0.1 })] }))).toBe(false);
		expect(schemaAccepts(validInput({ confidence: 2 }))).toBe(false);
	});

	test("keeps the native 80-character title limit advisory rather than failing the tool", () => {
		expect(schemaAccepts(validInput({ findings: [validFinding({ title: "x".repeat(81) })] }))).toBe(true);
	});

	test("rejects non-positive or non-integer line numbers", () => {
		for (const lines of [{ line_start: 0 }, { line_start: -3 }, { line_end: 0 }, { line_start: 1.5 }]) {
			expect(schemaAccepts(validInput({ findings: [validFinding(lines)] }))).toBe(false);
		}
	});

	test("rejects reversed line ranges", () => {
		expect(schemaAccepts(validInput({ findings: [validFinding({ line_start: 20, line_end: 10 })] }))).toBe(false);
	});

	test("accepts long, single-line, and empty finding ranges", () => {
		expect(schemaAccepts(validInput({ findings: [validFinding({ line_start: 1, line_end: 42 })] }))).toBe(true);
		expect(schemaAccepts(validInput({ findings: [validFinding({ line_start: 7, line_end: 7 })] }))).toBe(true);
		expect(schemaAccepts(validInput({ findings: [] }))).toBe(true);
	});

	test("requires findings and every declared field", () => {
		const withoutFindings = { ...validInput() } as Record<string, unknown>;
		delete withoutFindings.findings;
		expect(schemaAccepts(withoutFindings)).toBe(false);

		const finding = { ...validFinding() } as Record<string, unknown>;
		delete finding.title;
		expect(schemaAccepts(validInput({ findings: [finding as unknown as ReviewFindingInput] }))).toBe(false);
	});

	test("emits additionalProperties false and descriptions at every object level", () => {
		const json = parameters.toJsonSchema() as {
			additionalProperties?: unknown;
			properties?: Record<
				string,
				{
					description?: string;
					items?: {
						additionalProperties?: unknown;
						properties?: Record<string, { description?: string }>;
					};
				}
			>;
		};
		expect(json.additionalProperties).toBe(false);
		expect(json.properties?.findings?.items?.additionalProperties).toBe(false);
		for (const name of ["scope", "overall_correctness", "explanation", "recommendation", "confidence", "findings"]) {
			expect(typeof json.properties?.[name]?.description).toBe("string");
		}
		const findingProperties = json.properties?.findings?.items?.properties;
		expect(findingProperties?.body?.description).not.toContain("how to fix");
		expect(findingProperties?.recommendation?.description).toContain("recommended action");
	});
});
