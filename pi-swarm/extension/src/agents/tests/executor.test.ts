import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import { buildAgentRunName, ensureAgentDir, sanitizeAgentSpawnEnv } from "../executor.ts";

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

describe("sanitizeAgentSpawnEnv", () => {
	it("removes daemon report-identity vars while preserving allowed env values", () => {
		const env = sanitizeAgentSpawnEnv({
			BASECAMP_REPORT_TOKEN: "report-token",
			BASECAMP_AGENT_ID: "agent-id",
			BASECAMP_RUN_ID: "run-id",
			BASECAMP_DAEMON_UDS: "/tmp/daemon.sock",
			BASECAMP_PROJECT: "proj",
			BASECAMP_PARENT_SESSION: "parent-session",
			BASECAMP_AGENT_DEPTH: "2",
			BASECAMP_AGENT_MAX_DEPTH: "9",
			OPENAI_API_KEY: "openai-key",
			CUSTOM_API_KEY: "custom-key",
		});

		assert.equal(env.BASECAMP_REPORT_TOKEN, undefined);
		assert.equal(env.BASECAMP_AGENT_ID, undefined);
		assert.equal(env.BASECAMP_RUN_ID, undefined);
		assert.equal(env.BASECAMP_DAEMON_UDS, undefined);
		assert.equal(env.BASECAMP_PROJECT, "proj");
		assert.equal(env.BASECAMP_PARENT_SESSION, "parent-session");
		assert.equal(env.BASECAMP_AGENT_DEPTH, "2");
		assert.equal(env.BASECAMP_AGENT_MAX_DEPTH, "9");
		assert.equal(env.OPENAI_API_KEY, "openai-key");
		assert.equal(env.CUSTOM_API_KEY, "custom-key");
	});
});
