import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it } from "node:test";

const agentsDir = path.resolve(import.meta.dirname, "..", "..", "core", "swarm", "agents", "builtin");

function prompt(name: string): string {
	return fs.readFileSync(path.join(agentsDir, `${name}.md`), "utf8");
}

describe("reviewer persona methods", () => {
	it("keeps each established process and adds its focused falsification probe", () => {
		const contracts: Record<string, string[]> = {
			"general-reviewer": [
				"Read changed code and context",
				"Establish contracts and invariants",
				"Probe counterexamples",
			],
			"security-specialist": ["Identify attack surface", "Resolve actual identities", "Verify exploitability"],
			"testing-specialist": ["Map coverage", "Apply the counterfactual", "Evaluate quality"],
			"docs-specialist": ["Review systematically", "Trace each claim to behavior", "Reconcile representations"],
			"code-clarity-specialist": ["Assess maintainability", "Check semantic visibility", "Prioritize by impact"],
			"conventions-specialist": ["Cite where each convention is established", "Locate the canonical owner"],
		};

		for (const [reviewer, expected] of Object.entries(contracts)) {
			const content = prompt(reviewer);
			for (const token of expected) {
				assert.ok(content.includes(token), `${reviewer} should retain ${token}`);
			}
		}
	});

	it("defines integration as a distinct cross-boundary lens", () => {
		const content = prompt("integration-specialist");
		for (const token of [
			"Contract parity",
			"Data invariants",
			"Semantic parity",
			"Migration and rollout",
			"Operational completion",
		]) {
			assert.ok(content.includes(token), `integration specialist should cover ${token}`);
		}
	});
});
