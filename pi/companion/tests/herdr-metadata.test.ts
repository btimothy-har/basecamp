import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
	buildHerdrMetadata,
	buildHerdrMetadataArgs,
	createHerdrMetadataSeqBase,
	nextHerdrMetadataSeq,
	reportHerdrMetadata,
	resetHerdrMetadataSeqForTest,
	sanitizeHerdrMetadataField,
	shouldReportHerdrMetadata,
} from "../herdr/metadata.ts";
import type { CompanionSnapshot } from "../snapshot/model.ts";

function snapshot(overrides: Partial<CompanionSnapshot> = {}): CompanionSnapshot {
	return {
		version: 1,
		sessionId: "session-1",
		title: null,
		updatedAt: "2025-01-02T03:04:05.000Z",
		goal: null,
		tasks: [],
		progress: { completed: 0, total: 0 },
		agentMode: null,
		worktree: null,
		repoName: null,
		model: null,
		skillsUsed: [],
		effectiveCwd: "/tmp/repo",
		...overrides,
	};
}

function createMockPi(execHandler: () => unknown = () => ({ code: 0, stdout: "", stderr: "" })) {
	const execCalls: Array<{ command: string; args: string[] }> = [];
	const pi = {
		async exec(command: string, args: string[]) {
			execCalls.push({ command, args });
			return execHandler();
		},
	};
	return { pi: pi as unknown as ExtensionAPI, execCalls };
}

describe("companion/herdr-metadata", () => {
	afterEach(() => {
		delete process.env.HERDR_ENV;
		delete process.env.HERDR_PANE_ID;
		delete process.env.HERDR_SOCKET_PATH;
		delete process.env.BASECAMP_AGENT_DEPTH;
		resetHerdrMetadataSeqForTest();
	});

	it("guards reporting to primary Herdr panes with required env", () => {
		assert.equal(
			shouldReportHerdrMetadata({
				herdrEnv: "1",
				herdrPaneId: "w8:p1",
				herdrSocketPath: "/tmp/herdr.sock",
				agentDepth: 0,
			}),
			true,
		);
		assert.equal(
			shouldReportHerdrMetadata({
				herdrEnv: "0",
				herdrPaneId: "w8:p1",
				herdrSocketPath: "/tmp/herdr.sock",
				agentDepth: 0,
			}),
			false,
		);
		assert.equal(
			shouldReportHerdrMetadata({
				herdrEnv: "1",
				herdrSocketPath: "/tmp/herdr.sock",
				agentDepth: 0,
			}),
			false,
		);
		assert.equal(
			shouldReportHerdrMetadata({
				herdrEnv: "1",
				herdrPaneId: "w8:p1",
				herdrSocketPath: "/tmp/herdr.sock",
				agentDepth: 1,
			}),
			false,
		);
	});

	it("sanitizes collapsed text and truncates Herdr fields", () => {
		assert.equal(sanitizeHerdrMetadataField("  hello\n\tworld\u0000again  ", 14), "hello world ag");
		const metadata = buildHerdrMetadata(
			snapshot({
				title: `Title ${"x".repeat(100)}`,
				tasks: [{ label: `Active ${"y".repeat(100)}`, status: "active" }],
			}),
		);

		assert.equal(metadata.title.length, 80);
		assert.equal(metadata.displayAgent, "pi");
		assert.equal(metadata.customStatus.length, 32);
		assert.equal(metadata.customStatus, `Active ${"y".repeat(25)}`);
	});

	it("uses sanitized fallbacks for blank title and status candidates", () => {
		const metadata = buildHerdrMetadata(
			snapshot({
				sessionId: "session-fallback",
				title: " \n\t ",
				tasks: [{ label: " \u0000 ", status: "active" }],
				worktree: { label: " \t ", branch: null, path: "/tmp/wt" },
				agentMode: "planning",
				repoName: "repo-name",
			}),
		);

		assert.equal(metadata.title, "repo-name");
		assert.equal(metadata.customStatus, "planning");
	});

	it("uses waiting state before active task and the existing fallbacks", () => {
		const activeTaskSnapshot = snapshot({
			tasks: [{ label: "Active task", status: "active" }],
			worktree: { label: "worktree-label", branch: null, path: "/tmp/wt" },
			agentMode: "work",
			repoName: "repo-name",
		});

		assert.equal(
			buildHerdrMetadata(activeTaskSnapshot, {
				primaryIdle: false,
				waitingForAgents: false,
				activeAgentCount: 2,
			}).customStatus,
			"Active task",
		);
		assert.equal(
			buildHerdrMetadata(activeTaskSnapshot, {
				primaryIdle: true,
				waitingForAgents: false,
				activeAgentCount: 1,
			}).customStatus,
			"waiting on 1 agent",
		);
		assert.equal(
			buildHerdrMetadata(activeTaskSnapshot, {
				primaryIdle: false,
				waitingForAgents: true,
				activeAgentCount: 2,
			}).customStatus,
			"waiting on 2 agents",
		);
		assert.equal(
			buildHerdrMetadata(activeTaskSnapshot, {
				primaryIdle: false,
				waitingForAgents: true,
				activeAgentCount: null,
			}).customStatus,
			"waiting on agents",
		);
		assert.equal(
			buildHerdrMetadata(activeTaskSnapshot, {
				primaryIdle: true,
				waitingForAgents: false,
				activeAgentCount: 0,
			}).customStatus,
			"Active task",
		);

		assert.equal(
			buildHerdrMetadata(
				snapshot({
					tasks: [{ label: "Active task", status: "active" }],
					worktree: { label: "worktree-label", branch: null, path: "/tmp/wt" },
					agentMode: "work",
					repoName: "repo-name",
				}),
			).customStatus,
			"Active task",
		);
		assert.equal(
			buildHerdrMetadata(
				snapshot({
					worktree: { label: "worktree-label", branch: null, path: "/tmp/wt" },
					agentMode: "work",
					repoName: "repo-name",
				}),
			).customStatus,
			"worktree-label",
		);
		assert.equal(
			buildHerdrMetadata(snapshot({ agentMode: "planning", repoName: "repo-name" })).customStatus,
			"planning",
		);
		assert.equal(buildHerdrMetadata(snapshot({ repoName: "repo-name" })).customStatus, "repo-name");
	});

	it("builds report-metadata args with source, metadata, and sequence", () => {
		assert.deepEqual(buildHerdrMetadataArgs("w8:p1", snapshot({ title: "My title", repoName: "repo" }), 7), [
			"pane",
			"report-metadata",
			"w8:p1",
			"--source",
			"basecamp.pi",
			"--agent",
			"pi",
			"--applies-to-source",
			"herdr:pi",
			"--display-agent",
			"pi",
			"--title",
			"My title",
			"--custom-status",
			"repo",
			"--seq",
			"7",
		]);
	});

	it("uses a time- and process-based monotonic sequence", () => {
		assert.equal(createHerdrMetadataSeqBase(1_000, 42), 1_000_042);
		assert.notEqual(createHerdrMetadataSeqBase(1_000, 42), createHerdrMetadataSeqBase(1_000, 43));

		resetHerdrMetadataSeqForTest(4);
		assert.equal(nextHerdrMetadataSeq(), 5);
		assert.equal(nextHerdrMetadataSeq(), 6);
	});

	it("reports to HERDR_PANE_ID and swallows exec failures", async () => {
		resetHerdrMetadataSeqForTest();
		process.env.HERDR_ENV = "1";
		process.env.HERDR_PANE_ID = "w8:p1";
		process.env.HERDR_SOCKET_PATH = "/tmp/herdr.sock";
		process.env.BASECAMP_AGENT_DEPTH = "0";
		const { pi, execCalls } = createMockPi(() => {
			throw new Error("herdr unavailable");
		});

		await assert.doesNotReject(() => reportHerdrMetadata(pi, snapshot({ title: "Title" })));

		assert.deepEqual(execCalls, [
			{
				command: "herdr",
				args: buildHerdrMetadataArgs("w8:p1", snapshot({ title: "Title" }), 1),
			},
		]);
	});

	it("skips exec outside Herdr or in subagents", async () => {
		const { pi, execCalls } = createMockPi();

		await reportHerdrMetadata(pi, snapshot());
		process.env.HERDR_ENV = "1";
		process.env.HERDR_PANE_ID = "w8:p1";
		process.env.HERDR_SOCKET_PATH = "/tmp/herdr.sock";
		process.env.BASECAMP_AGENT_DEPTH = "1";
		await reportHerdrMetadata(pi, snapshot());

		assert.deepEqual(execCalls, []);
	});
});
