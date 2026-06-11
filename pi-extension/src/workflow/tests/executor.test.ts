import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import { buildAgentRunName, ensureAgentDir } from "../agents/executor.ts";

describe("buildAgentRunName", () => {
	it("accepts readable suffixes and trims outer whitespace", () => {
		assert.equal(buildAgentRunName("agent-abc", "review-auth"), "agent-abc-review-auth");
		assert.equal(buildAgentRunName("agent-abc", "qa_1"), "agent-abc-qa_1");
		assert.equal(buildAgentRunName("agent-abc", "  review auth  "), "agent-abc-review auth");
	});

	it("rejects malformed suffixes", () => {
		assert.throws(() => buildAgentRunName("agent-abc", "../bad"), /Invalid agent run-name suffix/i);
		assert.throws(() => buildAgentRunName("agent-abc", "bad\\suffix"), /Invalid agent run-name suffix/i);
		assert.throws(() => buildAgentRunName("agent-abc", "foo/../bar"), /Invalid agent run-name suffix/i);
		assert.throws(() => buildAgentRunName("agent-abc", ".."), /Invalid agent run-name suffix/i);
		assert.throws(() => buildAgentRunName("agent-abc", "bad\nname"), /Invalid agent run-name suffix/i);
		assert.throws(() => buildAgentRunName("agent-abc", "   "), /suffix cannot be empty/i);
	});
});

describe("ensureAgentDir", () => {
	it("defends path traversal attempts outside the base agent directory", () => {
		assert.throws(() => ensureAgentDir("../outside"), /outside basecamp-agents directory/i);
	});

	it("creates safe directories under basecamp-agents", () => {
		const name = `agent-valid-${randomUUID()}`;
		const dir = ensureAgentDir(name);
		try {
			assert.equal(path.basename(dir), name);
			assert.equal(path.dirname(dir), path.resolve(os.tmpdir(), "basecamp-agents"));
			assert.equal(fs.existsSync(dir), true);
		} finally {
			fs.rmSync(dir, { recursive: true, force: true });
		}
	});
});
