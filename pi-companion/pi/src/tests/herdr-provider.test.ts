import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
	buildHerdrCloseArgs,
	buildHerdrGetArgs,
	buildHerdrRunArgs,
	buildHerdrSplitArgs,
	createHerdrPaneProvider,
	parseHerdrPaneId,
	shouldCreateHerdrPane,
} from "../herdr-provider.ts";

type ExecResult = { code: number; stdout: string; stderr: string };
type ExecHandler = (command: string, args: string[]) => Promise<ExecResult> | ExecResult;

function createMockPi(execHandler: ExecHandler = () => ({ code: 0, stdout: "", stderr: "" })) {
	const execCalls: Array<{ command: string; args: string[] }> = [];
	const pi = {
		async exec(command: string, args: string[]) {
			execCalls.push({ command, args });
			return execHandler(command, args);
		},
	};
	return { pi: pi as unknown as ExtensionAPI, execCalls };
}

describe("panes/herdr-provider", () => {
	describe("shouldCreateHerdrPane", () => {
		it("returns true for interactive primary sessions with required Herdr env", () => {
			assert.equal(
				shouldCreateHerdrPane({
					herdrEnv: "1",
					herdrPaneId: "w8:p1",
					herdrSocketPath: "/tmp/herdr.sock",
					hasUI: true,
					agentDepth: 0,
				}),
				true,
			);
		});

		it("returns false when HERDR_ENV is not set to 1", () => {
			assert.equal(
				shouldCreateHerdrPane({
					herdrEnv: "0",
					herdrPaneId: "w8:p1",
					herdrSocketPath: "/tmp/herdr.sock",
					hasUI: true,
					agentDepth: 0,
				}),
				false,
			);
		});

		it("returns false when required pane or socket env is missing", () => {
			assert.equal(
				shouldCreateHerdrPane({
					herdrEnv: "1",
					herdrSocketPath: "/tmp/herdr.sock",
					hasUI: true,
					agentDepth: 0,
				}),
				false,
			);
			assert.equal(
				shouldCreateHerdrPane({
					herdrEnv: "1",
					herdrPaneId: "w8:p1",
					hasUI: true,
					agentDepth: 0,
				}),
				false,
			);
		});

		it("returns false when ui is unavailable or the session is a subagent", () => {
			assert.equal(
				shouldCreateHerdrPane({
					herdrEnv: "1",
					herdrPaneId: "w8:p1",
					herdrSocketPath: "/tmp/herdr.sock",
					hasUI: false,
					agentDepth: 0,
				}),
				false,
			);
			assert.equal(
				shouldCreateHerdrPane({
					herdrEnv: "1",
					herdrPaneId: "w8:p1",
					herdrSocketPath: "/tmp/herdr.sock",
					hasUI: true,
					agentDepth: 1,
				}),
				false,
			);
		});
	});

	describe("command builders", () => {
		it("builds split argv without a ratio", () => {
			assert.deepEqual(buildHerdrSplitArgs("w8:p1", "/tmp/worktree cwd"), [
				"pane",
				"split",
				"w8:p1",
				"--direction",
				"right",
				"--cwd",
				"/tmp/worktree cwd",
				"--no-focus",
				"--json",
			]);
		});

		it("builds run argv with the dashboard command as a single argument", () => {
			assert.deepEqual(buildHerdrRunArgs("w8:p2", "basecamp companion dashboard --snapshot '/tmp/snap.json'"), [
				"pane",
				"run",
				"w8:p2",
				"basecamp companion dashboard --snapshot '/tmp/snap.json'",
			]);
		});

		it("builds get and close argv", () => {
			assert.deepEqual(buildHerdrGetArgs("w8:p2"), ["pane", "get", "w8:p2", "--json"]);
			assert.deepEqual(buildHerdrCloseArgs("w8:p2"), ["pane", "close", "w8:p2"]);
		});
	});

	describe("parseHerdrPaneId", () => {
		it("extracts pane id from a nested pane object", () => {
			assert.equal(parseHerdrPaneId(JSON.stringify({ pane: { id: "w8:p2" } })), "w8:p2");
		});

		it("extracts pane id from common id keys", () => {
			assert.equal(parseHerdrPaneId(JSON.stringify({ id: "w8:p3" })), "w8:p3");
			assert.equal(parseHerdrPaneId(JSON.stringify({ paneId: "w8:p4" })), "w8:p4");
			assert.equal(parseHerdrPaneId(JSON.stringify({ pane_id: "w8:p5" })), "w8:p5");
		});

		it("extracts pane id from nested arrays and objects", () => {
			assert.equal(parseHerdrPaneId(JSON.stringify({ panes: [{ id: "w8:p6" }] })), "w8:p6");
		});

		it("falls back to the first Herdr-shaped id in non-json output", () => {
			assert.equal(parseHerdrPaneId("created pane w8:p7"), "w8:p7");
		});

		it("accepts non-numeric workspace and pane suffixes", () => {
			assert.equal(parseHerdrPaneId(JSON.stringify({ pane: { id: "wB:p1" } })), "wB:p1");
			assert.equal(parseHerdrPaneId(JSON.stringify({ pane: { id: "wfoo:pbar" } })), "wfoo:pbar");
		});

		it("returns null for empty, malformed, or unrelated output", () => {
			assert.equal(parseHerdrPaneId(""), null);
			assert.equal(parseHerdrPaneId(JSON.stringify({ pane: { id: "%2" } })), null);
			assert.equal(parseHerdrPaneId("created pane"), null);
		});
	});

	describe("createHerdrPaneProvider", () => {
		it("splits from the env pane, runs the dashboard command, and returns the new pane id", async () => {
			const provider = createHerdrPaneProvider({
				herdrEnv: "1",
				herdrPaneId: "w8:p1",
				herdrSocketPath: "/tmp/herdr.sock",
				hasUI: true,
				agentDepth: 0,
			});
			assert.ok(provider);
			const { pi, execCalls } = createMockPi((_command, args) => {
				if (args[1] === "split") return { code: 0, stdout: JSON.stringify({ pane: { id: "w8:p2" } }), stderr: "" };
				return { code: 0, stdout: "", stderr: "" };
			});

			const paneId = await provider.createPane(pi, { cwd: "/tmp/worktree", command: "basecamp companion dashboard" });

			assert.equal(paneId, "w8:p2");
			assert.deepEqual(execCalls, [
				{ command: "herdr", args: buildHerdrSplitArgs("w8:p1", "/tmp/worktree") },
				{ command: "herdr", args: buildHerdrRunArgs("w8:p2", "basecamp companion dashboard") },
			]);
		});

		it("returns null and does not run the dashboard command when split output has no pane id", async () => {
			const provider = createHerdrPaneProvider({
				herdrEnv: "1",
				herdrPaneId: "w8:p1",
				herdrSocketPath: "/tmp/herdr.sock",
				hasUI: true,
				agentDepth: 0,
			});
			assert.ok(provider);
			const { pi, execCalls } = createMockPi(() => ({ code: 0, stdout: JSON.stringify({ pane: {} }), stderr: "" }));

			const paneId = await provider.createPane(pi, { cwd: "/tmp/worktree", command: "basecamp companion dashboard" });

			assert.equal(paneId, null);
			assert.deepEqual(execCalls, [{ command: "herdr", args: buildHerdrSplitArgs("w8:p1", "/tmp/worktree") }]);
		});

		it("returns true when Herdr confirms the stored pane exists", async () => {
			const provider = createHerdrPaneProvider({
				herdrEnv: "1",
				herdrPaneId: "w8:p1",
				herdrSocketPath: "/tmp/herdr.sock",
				hasUI: true,
				agentDepth: 0,
			});
			assert.ok(provider);
			const { pi, execCalls } = createMockPi(() => ({
				code: 0,
				stdout: JSON.stringify({ pane: { id: "w8:p2" } }),
				stderr: "",
			}));

			assert.equal(await provider.paneStillExists(pi, "w8:p2"), true);
			assert.deepEqual(execCalls, [{ command: "herdr", args: buildHerdrGetArgs("w8:p2") }]);
		});

		it("returns false when Herdr confirms the stored pane is gone", async () => {
			const provider = createHerdrPaneProvider({
				herdrEnv: "1",
				herdrPaneId: "w8:p1",
				herdrSocketPath: "/tmp/herdr.sock",
				hasUI: true,
				agentDepth: 0,
			});
			assert.ok(provider);
			const { pi } = createMockPi(() => ({ code: 1, stdout: "", stderr: "pane not found" }));

			assert.equal(await provider.paneStillExists(pi, "w8:p2"), false);
		});

		it("treats Herdr liveness errors as alive/inconclusive", async () => {
			const provider = createHerdrPaneProvider({
				herdrEnv: "1",
				herdrPaneId: "w8:p1",
				herdrSocketPath: "/tmp/herdr.sock",
				hasUI: true,
				agentDepth: 0,
			});
			assert.ok(provider);
			const { pi, execCalls } = createMockPi(() => {
				throw new Error("Herdr unavailable");
			});

			assert.equal(await provider.paneStillExists(pi, "w8:p2"), true);
			assert.deepEqual(execCalls, [{ command: "herdr", args: buildHerdrGetArgs("w8:p2") }]);
		});
	});
});
