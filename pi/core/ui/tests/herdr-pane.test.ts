import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { shellQuote } from "#core/host/shell.ts";
import {
	checkHerdrEligibility,
	closeHerdrTab,
	type HerdrEnv,
	openHerdrTab,
	runInHerdrPane,
} from "#core/ui/herdr-pane.ts";

interface ExecCall {
	command: string;
	args: string[];
}

type ExecResult = { code: number; stdout: string; stderr: string; killed: boolean };

function mockPi(handler: (args: string[]) => Promise<ExecResult>): Pick<ExtensionAPI, "exec"> & { calls: ExecCall[] } {
	const calls: ExecCall[] = [];
	return {
		calls,
		exec: async (command: string, args: string[]) => {
			calls.push({ command, args });
			return await handler(args);
		},
	} as unknown as Pick<ExtensionAPI, "exec"> & { calls: ExecCall[] };
}

const eligibleEnv: HerdrEnv = {
	HERDR_ENV: "1",
	HERDR_SOCKET_PATH: "/tmp/herdr.sock",
	HERDR_PANE_ID: "w1:p1",
	HERDR_WORKSPACE_ID: "w1",
};

const TAB_CREATED = JSON.stringify({
	id: "cli:tab:create",
	result: {
		root_pane: { pane_id: "w38:p6", tab_id: "w38:t5" },
		tab: { tab_id: "w38:t5", label: "diff: basecamp", workspace_id: "w38" },
		type: "tab_created",
	},
});

function ok(stdout: string): Promise<ExecResult> {
	return Promise.resolve({ code: 0, stdout, stderr: "", killed: false });
}

describe("checkHerdrEligibility", () => {
	it("returns null for an eligible primary session", () => {
		assert.equal(checkHerdrEligibility({ env: eligibleEnv, subject: "diffs" }), null);
		assert.equal(checkHerdrEligibility({ env: eligibleEnv, hasUI: true, subject: "diffs" }), null);
	});

	it("reports each missing Herdr environment signal", () => {
		const cases: [HerdrEnv, string][] = [
			[{ ...eligibleEnv, HERDR_ENV: undefined }, "missing-herdr-env"],
			[{ ...eligibleEnv, HERDR_SOCKET_PATH: undefined }, "missing-herdr-socket-path"],
			[{ ...eligibleEnv, HERDR_PANE_ID: undefined }, "missing-herdr-pane-id"],
		];
		for (const [env, reason] of cases) {
			assert.equal(checkHerdrEligibility({ env, subject: "diffs" })?.reason, reason);
		}
	});

	it("refuses subagents and headless sessions", () => {
		const subagent = checkHerdrEligibility({ env: { ...eligibleEnv, BASECAMP_AGENT_DEPTH: "1" }, subject: "diffs" });
		assert.equal(subagent?.reason, "subagent");
		assert.equal(subagent?.detail, "only primary sessions can open diffs in Herdr.");
		assert.equal(checkHerdrEligibility({ env: eligibleEnv, hasUI: false, subject: "diffs" })?.reason, "headless");
	});

	it("treats blank depth as primary and malformed depth as a subagent", () => {
		assert.equal(checkHerdrEligibility({ env: { ...eligibleEnv, BASECAMP_AGENT_DEPTH: "  " }, subject: "d" }), null);
		assert.equal(
			checkHerdrEligibility({ env: { ...eligibleEnv, BASECAMP_AGENT_DEPTH: "nope" }, subject: "d" })?.reason,
			"subagent",
		);
	});
});

describe("openHerdrTab", () => {
	it("always sends --workspace and parses the created pane and tab ids", async () => {
		const pi = mockPi(() => ok(TAB_CREATED));

		const result = await openHerdrTab(pi, {
			workspaceId: "w38",
			cwd: "/repo",
			label: "diff: basecamp",
			env: { HUNK_DISABLE_UPDATE_NOTICE: "1" },
		});

		assert.equal(result.status, "ok");
		assert.deepEqual(result.status === "ok" ? result.value : null, { paneId: "w38:p6", tabId: "w38:t5" });
		assert.deepEqual(pi.calls[0], {
			command: "herdr",
			args: [
				"tab",
				"create",
				"--workspace",
				"w38",
				"--cwd",
				"/repo",
				"--label",
				"diff: basecamp",
				"--no-focus",
				"--env",
				"HUNK_DISABLE_UPDATE_NOTICE=1",
			],
		});
	});

	it("fails without throwing on nonzero exit, unparsable output, and exec errors", async () => {
		const nonzero = await openHerdrTab(
			mockPi(() => Promise.resolve({ code: 2, stdout: "", stderr: "x", killed: false })),
			{
				workspaceId: "w1",
				cwd: "/repo",
				label: "l",
			},
		);
		assert.equal(nonzero.status, "failed");
		assert.equal(nonzero.status === "failed" ? nonzero.exitCode : null, 2);

		const garbage = await openHerdrTab(
			mockPi(() => ok("not json")),
			{ workspaceId: "w1", cwd: "/repo", label: "l" },
		);
		assert.equal(garbage.status, "failed");

		const missingIds = await openHerdrTab(
			mockPi(() => ok('{"result":{}}')),
			{
				workspaceId: "w1",
				cwd: "/repo",
				label: "l",
			},
		);
		assert.equal(missingIds.status, "failed");

		const threw = await openHerdrTab(
			mockPi(() => Promise.reject(new Error("herdr not found"))),
			{ workspaceId: "w1", cwd: "/repo", label: "l" },
		);
		assert.equal(threw.status, "failed");
		assert.match(threw.status === "failed" ? (threw.error ?? "") : "", /herdr not found/);
	});
});

describe("runInHerdrPane", () => {
	it("single-quotes every argument, including the command name", async () => {
		const pi = mockPi(() => ok(""));

		await runInHerdrPane(pi, "w38:p6", ["hunk", "diff", "43e3afd6"]);

		assert.deepEqual(pi.calls[0]?.args, ["pane", "run", "w38:p6", "'hunk'", "'diff'", "'43e3afd6'"]);
	});

	it("neutralizes shell metacharacters that a git ref may legally contain", async () => {
		const pi = mockPi(() => ok(""));

		await runInHerdrPane(pi, "w38:p6", ["hunk", "diff", "a;touch /tmp/x", "$HOME", "`id`"]);

		assert.deepEqual(pi.calls[0]?.args.slice(3), ["'hunk'", "'diff'", "'a;touch /tmp/x'", "'$HOME'", "'`id`'"]);
	});
});

describe("shellQuote", () => {
	it("produces arguments a real shell evaluates literally", () => {
		const dir = fs.mkdtempSync(path.join(os.tmpdir(), "herdr-quote-"));
		try {
			const marker = path.join(dir, "INJECTED");
			const hostile = `a;touch ${marker}`;
			// The quoted form is pasted into a shell verbatim, exactly as `herdr pane run` would.
			const stdout = execFileSync("/bin/sh", ["-c", `printf %s ${shellQuote(hostile)}`], { encoding: "utf8" });

			assert.equal(stdout, hostile);
			assert.equal(fs.existsSync(marker), false, "quoting must prevent the injected command from running");

			const withQuote = "it's";
			assert.equal(
				execFileSync("/bin/sh", ["-c", `printf %s ${shellQuote(withQuote)}`], { encoding: "utf8" }),
				withQuote,
			);
		} finally {
			fs.rmSync(dir, { recursive: true, force: true });
		}
	});
});

describe("closeHerdrTab", () => {
	it("closes by tab id", async () => {
		const pi = mockPi(() => ok('{"result":{"type":"ok"}}'));

		const result = await closeHerdrTab(pi, "w38:t5");

		assert.equal(result.status, "ok");
		assert.deepEqual(pi.calls[0]?.args, ["tab", "close", "w38:t5"]);
	});
});
