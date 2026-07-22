import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { Value } from "@sinclair/typebox/value";
import { ReportFindingsParams } from "../findings.ts";

const scope = { base: "origin/main", mergeBase: "abc1234", cwd: "/repo", label: "branch x → origin/main" };
const summary = "Synthesized review summary.";

const validFinding = {
	dimension: "security",
	severity: "high",
	file: "src/a.ts",
	lineStart: 1,
	lineEnd: 2,
	title: "t",
	detail: "d",
	remediation: null,
};

function payload(finding: Record<string, unknown>): unknown {
	return { scope, summary, findings: [finding] };
}

describe("ReportFindingsParams validation", () => {
	it("accepts a valid finding, with or without response", () => {
		assert.equal(Value.Check(ReportFindingsParams, payload(validFinding)), true);
		assert.equal(Value.Check(ReportFindingsParams, payload({ ...validFinding, response: "context" })), true);
	});

	it("accepts null for the nullable location and remediation fields", () => {
		assert.equal(
			Value.Check(
				ReportFindingsParams,
				payload({ ...validFinding, file: null, lineStart: null, lineEnd: null, remediation: null }),
			),
			true,
		);
	});

	it("rejects an out-of-range severity", () => {
		assert.equal(Value.Check(ReportFindingsParams, payload({ ...validFinding, severity: "moderate" })), false);
	});

	it("accepts the integration dimension and rejects an unknown dimension", () => {
		assert.equal(Value.Check(ReportFindingsParams, payload({ ...validFinding, dimension: "integration" })), true);
		assert.equal(Value.Check(ReportFindingsParams, payload({ ...validFinding, dimension: "performance" })), false);
	});

	it("rejects a finding missing the required dimension", () => {
		assert.equal(
			Value.Check(
				ReportFindingsParams,
				payload({
					severity: "high",
					file: null,
					lineStart: null,
					lineEnd: null,
					title: "t",
					detail: "d",
					remediation: null,
				}),
			),
			false,
		);
	});

	it("rejects an unknown extra property", () => {
		assert.equal(Value.Check(ReportFindingsParams, payload({ ...validFinding, bogus: true })), false);
	});

	it("requires a non-empty synthesized summary", () => {
		assert.equal(Value.Check(ReportFindingsParams, { scope, findings: [validFinding] }), false);
		assert.equal(Value.Check(ReportFindingsParams, { scope, summary: "", findings: [validFinding] }), false);
	});

	it("rejects a payload with no scope", () => {
		assert.equal(Value.Check(ReportFindingsParams, { summary, findings: [validFinding] }), false);
	});
});
