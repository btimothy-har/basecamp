import { describe, expect, test } from "bun:test";
import { execFileSync } from "node:child_process";
import type { ExecOptions, ExecResult, ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import {
	checkHerdrEligibility,
	closeHerdrPane,
	type HerdrEnv,
	type HerdrSkipReason,
	readHerdrPaneProcesses,
	runInHerdrPane,
	shellQuote,
	splitHerdrPane,
	withHerdrBlocked,
} from "../herdr.ts";

interface ExecCall {
	command: string;
	args: string[];
	options?: ExecOptions;
}

type HerdrExec = Pick<ExtensionAPI, "exec">;

function mockPi(handler: () => ExecResult | Promise<ExecResult>): { pi: HerdrExec; calls: ExecCall[] } {
	const calls: ExecCall[] = [];
	const pi: HerdrExec = {
		exec: (command: string, args: string[], options?: ExecOptions) => {
			calls.push({ command, args, options });
			return Promise.resolve().then(handler);
		},
	};
	return { pi, calls };
}

function ok(stdout: string): ExecResult {
	return { code: 0, stdout, stderr: "", killed: false };
}

const PANE_TARGET_JSON = JSON.stringify({ result: { pane: { pane_id: "w9:p2", tab_id: "w9:t1" } } });

const eligibleEnv: HerdrEnv = {
	HERDR_ENV: "1",
	HERDR_SOCKET_PATH: "/tmp/herdr.sock",
	HERDR_PANE_ID: "w1:p1",
	HERDR_WORKSPACE_ID: "w1",
};

describe("checkHerdrEligibility", () => {
	test("accepts a primary Herdr session with a UI", () => {
		expect(checkHerdrEligibility({ env: eligibleEnv, hasUI: true })).toBeNull();
	});

	const cases: [HerdrEnv, HerdrSkipReason][] = [
		[{ ...eligibleEnv, HERDR_ENV: undefined }, "missing-herdr-env"],
		[{ ...eligibleEnv, HERDR_SOCKET_PATH: undefined }, "missing-herdr-socket-path"],
		[{ ...eligibleEnv, HERDR_PANE_ID: undefined }, "missing-herdr-pane-id"],
	];
	for (const [env, reason] of cases) {
		test(`refuses with ${reason}`, () => {
			expect(checkHerdrEligibility({ env })?.reason).toBe(reason);
		});
	}

	test("refuses headless sessions", () => {
		expect(checkHerdrEligibility({ env: eligibleEnv, hasUI: false })?.reason).toBe("headless");
	});
});

describe("splitHerdrPane", () => {
	test("splits rightward at 50% with cwd and env, and parses the new pane target", async () => {
		const { pi, calls } = mockPi(() => ok(PANE_TARGET_JSON));
		const result = await splitHerdrPane(pi, {
			paneId: "w9:p1",
			cwd: "/repo",
			env: { HUNK_DISABLE_UPDATE_NOTICE: "1" },
		});
		expect(calls).toEqual([
			{
				command: "herdr",
				args: [
					"pane",
					"split",
					"w9:p1",
					"--direction",
					"right",
					"--ratio",
					"0.5",
					"--cwd",
					"/repo",
					"--no-focus",
					"--env",
					"HUNK_DISABLE_UPDATE_NOTICE=1",
				],
				options: { cwd: "/repo", timeout: 5000 },
			},
		]);
		expect(result.status).toBe("ok");
		if (result.status === "ok") expect(result.value).toEqual({ paneId: "w9:p2", tabId: "w9:t1" });
	});

	test("fails closed on malformed split output instead of inventing a pane id", async () => {
		for (const stdout of ["", "not json", '{"result":{}}', '{"result":{"pane":{"pane_id":"w9:p2"}}}']) {
			const { pi } = mockPi(() => ok(stdout));
			const result = await splitHerdrPane(pi, { paneId: "w9:p1", cwd: "/repo" });
			expect(result.status).toBe("failed");
			if (result.status === "failed") expect(result.message).toContain("unreadable output");
		}
	});

	test("reports a nonzero exit with its code", async () => {
		const { pi } = mockPi(() => ({ code: 1, stdout: "", stderr: "pane_not_found", killed: false }));
		const result = await splitHerdrPane(pi, { paneId: "w9:p1", cwd: "/repo" });
		expect(result.status).toBe("failed");
		if (result.status === "failed") {
			expect(result.exitCode).toBe(1);
			expect(result.message).toContain("exit code 1");
		}
	});

	test("fails closed when exec reports a timeout with a zero exit code", async () => {
		const { pi } = mockPi(() => ({ code: 0, stdout: PANE_TARGET_JSON, stderr: "deadline", killed: true }));
		const result = await splitHerdrPane(pi, { paneId: "w9:p1", cwd: "/repo" });
		expect(result.status).toBe("failed");
		if (result.status === "failed") expect(result.message).toContain("killed or timed out");
	});

	test("reports a thrown exec", async () => {
		const { pi } = mockPi(() => Promise.reject(new Error("herdr not found")));
		const result = await splitHerdrPane(pi, { paneId: "w9:p1", cwd: "/repo" });
		expect(result.status).toBe("failed");
		if (result.status === "failed") expect(result.error).toContain("herdr not found");
	});
});

describe("readHerdrPaneProcesses", () => {
	test("reads foreground process identities for the exact pane", async () => {
		const output = JSON.stringify({
			result: {
				process_info: {
					foreground_processes: [
						{ pid: 4242, argv: ["/opt/hunk", "patch", "/tmp/review.patch"] },
						{ pid: 4243, argv: ["git", "status"] },
					],
				},
			},
		});
		const { pi, calls } = mockPi(() => ok(output));

		const result = await readHerdrPaneProcesses(pi, "w9:p2");

		expect(result.status).toBe("ok");
		if (result.status === "ok") {
			expect(result.value).toEqual([
				{ pid: 4242, argv: ["/opt/hunk", "patch", "/tmp/review.patch"] },
				{ pid: 4243, argv: ["git", "status"] },
			]);
		}
		expect(calls[0]).toEqual({
			command: "herdr",
			args: ["pane", "process-info", "--pane", "w9:p2"],
			options: { timeout: 5000 },
		});
	});

	test("fails closed on malformed process identities", async () => {
		const output = JSON.stringify({
			result: { process_info: { foreground_processes: [{ pid: 0, argv: ["/opt/hunk"] }] } },
		});
		const { pi } = mockPi(() => ok(output));
		const result = await readHerdrPaneProcesses(pi, "w9:p2");
		expect(result.status).toBe("failed");
		if (result.status === "failed") expect(result.message).toContain("unreadable output");
	});
});

describe("runInHerdrPane", () => {
	test("single-quotes every argv element before it reaches the pane's shell", async () => {
		const { pi, calls } = mockPi(() => ok(""));
		await runInHerdrPane(pi, "w9:p2", ["/opt/hunk", "diff", "feat;rm -rf /", "--agent-context", "/tmp/a b.json"]);
		expect(calls[0]?.args).toEqual([
			"pane",
			"run",
			"w9:p2",
			"'/opt/hunk'",
			"'diff'",
			"'feat;rm -rf /'",
			"'--agent-context'",
			"'/tmp/a b.json'",
		]);
	});

	test("escapes embedded single quotes", () => {
		expect(shellQuote("it's")).toBe("'it'\\''s'");
	});

	test("produces arguments a real shell evaluates literally", () => {
		const hostile = "a;touch /tmp/omp-diff-INJECTED";
		// The quoted form is pasted into a shell verbatim, exactly as `herdr pane run` would.
		const stdout = execFileSync("/bin/sh", ["-c", `printf %s ${shellQuote(hostile)}`], { encoding: "utf8" });
		expect(stdout).toBe(hostile);
	});
});

describe("closeHerdrPane", () => {
	test("closes by exact pane id", async () => {
		const { pi, calls } = mockPi(() => ok('{"result":{"type":"ok"}}'));
		const result = await closeHerdrPane(pi, "w9:p2");
		expect(result.status).toBe("ok");
		expect(calls[0]?.args).toEqual(["pane", "close", "w9:p2"]);
	});
});

describe("withHerdrBlocked", () => {
	function mockEvents(): { pi: Pick<ExtensionAPI, "events">; emitted: { channel: string; data: unknown }[] } {
		const emitted: { channel: string; data: unknown }[] = [];
		// Structural stand-in for EventBus: emit is the only member the lifecycle uses.
		const pi = {
			events: { emit: (channel: string, data: unknown) => void emitted.push({ channel, data }) },
		} as unknown as Pick<ExtensionAPI, "events">;
		return { pi, emitted };
	}

	test("emits blocked around the operation and returns its value", async () => {
		const { pi, emitted } = mockEvents();
		const value = await withHerdrBlocked(pi, "Reviewing in hunk", () => Promise.resolve("done"));
		expect(value).toBe("done");
		expect(emitted).toEqual([
			{ channel: "herdr:blocked", data: { active: true, label: "Reviewing in hunk" } },
			{ channel: "herdr:blocked", data: { active: false } },
		]);
	});

	test("emits the unblock even when the operation throws", async () => {
		const { pi, emitted } = mockEvents();
		await expect(
			withHerdrBlocked(pi, "Reviewing in hunk", () => Promise.reject(new Error("cancelled"))),
		).rejects.toThrow("cancelled");
		expect(emitted.map((event) => event.data)).toEqual([
			{ active: true, label: "Reviewing in hunk" },
			{ active: false },
		]);
	});
});
