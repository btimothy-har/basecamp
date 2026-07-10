import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { buildAgentEnv, buildAgentTitleBase, processEnvForSpawn } from "../launch.ts";
import { installDaemonToolTestHooks } from "./harness.ts";

describe("agent launch helpers", () => {
	installDaemonToolTestHooks();

	describe("buildAgentEnv", () => {
		it("sets parent session as sibling group for spawned agents", () => {
			const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
			const priorProject = process.env.BASECAMP_PROJECT;
			const priorParent = process.env.BASECAMP_PARENT_SESSION;
			const priorSiblingGroup = process.env.BASECAMP_SIBLING_GROUP;
			const priorAgentHandle = process.env.BASECAMP_AGENT_HANDLE;
			process.env.BASECAMP_AGENT_DEPTH = "1";
			process.env.BASECAMP_PROJECT = "parent-project";
			process.env.BASECAMP_PARENT_SESSION = "old-parent";
			process.env.BASECAMP_SIBLING_GROUP = "old-sibling-group";
			process.env.BASECAMP_AGENT_HANDLE = "parent-handle";

			try {
				const env = buildAgentEnv({
					name: "agent-name",
					parentSession: "dispatcher-node",
					project: "child-project",
				});

				assert.equal(env.BASECAMP_PROJECT, "child-project");
				assert.equal(env.BASECAMP_PARENT_SESSION, "dispatcher-node");
				assert.equal(env.BASECAMP_SIBLING_GROUP, "dispatcher-node");
				assert.equal(env.BASECAMP_AGENT_DEPTH, "2");
				assert.equal(env.BASECAMP_AGENT_HANDLE, undefined);
			} finally {
				if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
				else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
				if (priorProject === undefined) delete process.env.BASECAMP_PROJECT;
				else process.env.BASECAMP_PROJECT = priorProject;
				if (priorParent === undefined) delete process.env.BASECAMP_PARENT_SESSION;
				else process.env.BASECAMP_PARENT_SESSION = priorParent;
				if (priorSiblingGroup === undefined) delete process.env.BASECAMP_SIBLING_GROUP;
				else process.env.BASECAMP_SIBLING_GROUP = priorSiblingGroup;
				if (priorAgentHandle === undefined) delete process.env.BASECAMP_AGENT_HANDLE;
				else process.env.BASECAMP_AGENT_HANDLE = priorAgentHandle;
			}
		});
	});

	describe("buildAgentTitleBase", () => {
		it("formats named/ad-hoc titles, compacts whitespace, and truncates long tasks", () => {
			assert.equal(buildAgentTitleBase("scout", "Investigate the auth flow"), "(scout) Investigate the auth flow");
			assert.equal(buildAgentTitleBase(undefined, "hello world"), "(Agent) hello world");
			assert.equal(buildAgentTitleBase("worker", "do   a\n  thing"), "(worker) do a thing");

			const longTask = "x".repeat(80);
			const truncated = buildAgentTitleBase("worker", longTask);
			assert.equal(truncated.endsWith("…"), true);
			assert.ok(truncated.length <= "(worker) ".length + 56);
		});
	});

	describe("processEnvForSpawn", () => {
		it("strips daemon report identity vars while preserving ordinary env", () => {
			const prior = {
				runId: process.env.BASECAMP_RUN_ID,
				reportToken: process.env.BASECAMP_REPORT_TOKEN,
				agentId: process.env.BASECAMP_AGENT_ID,
				daemonUds: process.env.BASECAMP_DAEMON_UDS,
				agentHandle: process.env.BASECAMP_AGENT_HANDLE,
				project: process.env.BASECAMP_PROJECT,
				apiKey: process.env.DAEMON_TEST_API_KEY,
			};
			process.env.BASECAMP_RUN_ID = "run-parent";
			process.env.BASECAMP_REPORT_TOKEN = "report-parent";
			process.env.BASECAMP_AGENT_ID = "agent-parent";
			process.env.BASECAMP_DAEMON_UDS = "/tmp/daemon-parent.sock";
			process.env.BASECAMP_AGENT_HANDLE = "parent-handle";
			process.env.BASECAMP_PROJECT = "proj-parent";
			process.env.DAEMON_TEST_API_KEY = "parent-api-key";

			try {
				const env = processEnvForSpawn();
				assert.equal(env.BASECAMP_RUN_ID, undefined);
				assert.equal(env.BASECAMP_REPORT_TOKEN, undefined);
				assert.equal(env.BASECAMP_AGENT_ID, undefined);
				assert.equal(env.BASECAMP_DAEMON_UDS, undefined);
				assert.equal(env.BASECAMP_AGENT_HANDLE, undefined);
				assert.equal(env.BASECAMP_PROJECT, "proj-parent");
				assert.equal(env.DAEMON_TEST_API_KEY, "parent-api-key");
			} finally {
				if (prior.runId === undefined) delete process.env.BASECAMP_RUN_ID;
				else process.env.BASECAMP_RUN_ID = prior.runId;
				if (prior.reportToken === undefined) delete process.env.BASECAMP_REPORT_TOKEN;
				else process.env.BASECAMP_REPORT_TOKEN = prior.reportToken;
				if (prior.agentId === undefined) delete process.env.BASECAMP_AGENT_ID;
				else process.env.BASECAMP_AGENT_ID = prior.agentId;
				if (prior.daemonUds === undefined) delete process.env.BASECAMP_DAEMON_UDS;
				else process.env.BASECAMP_DAEMON_UDS = prior.daemonUds;
				if (prior.agentHandle === undefined) delete process.env.BASECAMP_AGENT_HANDLE;
				else process.env.BASECAMP_AGENT_HANDLE = prior.agentHandle;
				if (prior.project === undefined) delete process.env.BASECAMP_PROJECT;
				else process.env.BASECAMP_PROJECT = prior.project;
				if (prior.apiKey === undefined) delete process.env.DAEMON_TEST_API_KEY;
				else process.env.DAEMON_TEST_API_KEY = prior.apiKey;
			}
		});
	});
});
