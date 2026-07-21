import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { lookupPullRequestStatus, type PullRequestState } from "../pr-status.ts";

type ExecOptions = Parameters<ExtensionAPI["exec"]>[2];
type ExecResult = Awaited<ReturnType<ExtensionAPI["exec"]>>;

interface ExecCall {
	command: string;
	args: string[];
	options?: ExecOptions;
}

function execResult(stdout = "", code = 0, stderr = ""): ExecResult {
	return { code, stdout, stderr, killed: false };
}

function createPi(handler: (call: ExecCall) => ExecResult | Promise<ExecResult>): ExtensionAPI {
	return {
		exec(command: string, args: string[], options?: ExecOptions): Promise<ExecResult> {
			return Promise.resolve(handler({ command, args, options }));
		},
	} as ExtensionAPI;
}

function response(
	overrides: Partial<{ number: unknown; url: unknown; state: unknown; isDraft: unknown }> = {},
): string {
	return JSON.stringify({
		number: 297,
		url: "https://github.com/example/basecamp/pull/297",
		state: "OPEN",
		isDraft: false,
		...overrides,
	});
}

describe("lookupPullRequestStatus", () => {
	it("queries the current checkout with a timeout and cancellation signal", async () => {
		const controller = new AbortController();
		const pi = createPi((call) => {
			assert.equal(call.command, "gh");
			assert.deepEqual(call.args, ["pr", "view", "--json", "number,url,state,isDraft"]);
			assert.deepEqual(call.options, {
				cwd: "/worktrees/basecamp/feature",
				timeout: 10_000,
				signal: controller.signal,
			});
			return execResult(`${response()}\n`);
		});

		assert.deepEqual(await lookupPullRequestStatus(pi, "/worktrees/basecamp/feature", controller.signal), {
			number: 297,
			url: "https://github.com/example/basecamp/pull/297",
			state: "OPEN",
			isDraft: false,
		});
	});

	it("accepts every pull request state and draft status", async (t) => {
		const cases: Array<{ state: PullRequestState; isDraft: boolean }> = [
			{ state: "OPEN", isDraft: false },
			{ state: "OPEN", isDraft: true },
			{ state: "MERGED", isDraft: false },
			{ state: "CLOSED", isDraft: false },
		];

		for (const expected of cases) {
			await t.test(`${expected.state.toLowerCase()}${expected.isDraft ? " draft" : ""}`, async () => {
				const pi = createPi(() => execResult(response(expected)));
				const status = await lookupPullRequestStatus(pi, "/repo");

				assert.equal(status?.state, expected.state);
				assert.equal(status?.isDraft, expected.isDraft);
			});
		}
	});

	it("normalizes HTTP URLs before returning them", async () => {
		const unsafeControl = "https://github.com/example/basecamp/pull/297\u001b]8;;https://evil.example";
		const pi = createPi(() => execResult(response({ url: unsafeControl })));

		const status = await lookupPullRequestStatus(pi, "/repo");

		assert.ok(status);
		assert.equal(status.url.includes("\u001b"), false);
		assert.match(status.url, /%1B/);
	});

	it("rejects malformed or unsafe responses", async (t) => {
		const invalidOutputs = [
			"",
			"not json",
			"[]",
			response({ number: "297" }),
			response({ number: 0 }),
			response({ number: 1.5 }),
			response({ state: "UNKNOWN" }),
			response({ isDraft: "false" }),
			response({ url: 297 }),
			response({ url: "javascript:alert(1)" }),
			response({ url: "https://user:secret@github.com/example/basecamp/pull/297" }),
		];

		for (const [index, output] of invalidOutputs.entries()) {
			await t.test(`invalid response ${index + 1}`, async () => {
				const pi = createPi(() => execResult(output));
				assert.equal(await lookupPullRequestStatus(pi, "/repo"), null);
			});
		}
	});

	it("returns no observation when gh exits unsuccessfully", async () => {
		const pi = createPi(() => execResult("", 1, "no pull requests found"));

		assert.equal(await lookupPullRequestStatus(pi, "/repo"), null);
	});

	it("returns no observation when command execution throws", async () => {
		const pi = createPi(() => {
			throw new Error("gh is unavailable");
		});

		assert.equal(await lookupPullRequestStatus(pi, "/repo"), null);
	});

	it("returns no observation when command execution is aborted", async () => {
		const controller = new AbortController();
		controller.abort();
		const pi = createPi((call) => {
			assert.equal(call.options?.signal, controller.signal);
			throw new DOMException("aborted", "AbortError");
		});

		assert.equal(await lookupPullRequestStatus(pi, "/repo", controller.signal), null);
	});
});
