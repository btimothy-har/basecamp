import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerDirtyWorktreeReminder } from "../dirty-reminder.ts";
import type { WorkspaceState } from "../state.ts";
import { activeWorktreeState, baseWorkspaceState, WORKTREE_DIR } from "./guards-harness.ts";

type EventHandler = () => Promise<void> | void;
type MessageStartHandler = (event: { message: { role: string; customType?: string } }) => void;

interface SentReminder {
	message: { customType: string; content: string; display: boolean };
	options: { deliverAs: string; triggerTurn?: boolean };
}

function createHarness(
	options: {
		state?: WorkspaceState;
		readOnly?: boolean;
		subagent?: boolean;
		status?: { code: number; stdout: string; stderr: string; killed?: boolean };
		execError?: Error;
		sendError?: Error;
	} = {},
) {
	let registeredMessageStart = false;
	let registeredEnd = false;
	let registeredSettled = false;
	let messageStartHandler: MessageStartHandler = () => {
		throw new Error("message_start handler was not registered");
	};
	let endHandler: EventHandler = () => {
		throw new Error("agent_end handler was not registered");
	};
	let settledHandler: EventHandler = () => {
		throw new Error("agent_settled handler was not registered");
	};
	let execCalls = 0;
	const sent: SentReminder[] = [];
	const state = options.state ?? activeWorktreeState();
	const status = options.status ?? { code: 0, stdout: " M src/file.ts\n", stderr: "" };
	const pi = {
		on(name: string, handler: EventHandler | MessageStartHandler) {
			if (name === "message_start") {
				registeredMessageStart = true;
				messageStartHandler = handler as MessageStartHandler;
			}
			if (name === "agent_end") {
				registeredEnd = true;
				endHandler = handler as EventHandler;
			}
			if (name === "agent_settled") {
				registeredSettled = true;
				settledHandler = handler as EventHandler;
			}
		},
		async exec(command: string, args: string[]) {
			execCalls++;
			assert.equal(command, "git");
			assert.deepEqual(args, ["-C", WORKTREE_DIR, "status", "--porcelain"]);
			if (options.execError) throw options.execError;
			return status;
		},
		sendMessage(message: SentReminder["message"], sendOptions: SentReminder["options"]) {
			if (options.sendError) throw options.sendError;
			sent.push({ message, options: sendOptions });
		},
	} as unknown as ExtensionAPI;

	registerDirtyWorktreeReminder(pi, {
		getState: () => state,
		isReadOnly: () => options.readOnly === true,
		isSubagent: () => options.subagent === true,
	});
	assert.equal(registeredMessageStart, true);
	assert.equal(registeredEnd, true);
	assert.equal(registeredSettled, true);

	const startMessage = (role: string, customType?: string) => messageStartHandler({ message: { role, customType } });
	return {
		startMessage,
		startReminder: () => startMessage("custom", "basecamp-dirty-worktree-reminder"),
		end: endHandler,
		settle: settledHandler,
		sent,
		execCalls: () => execCalls,
	};
}

describe("dirty worktree reminder", () => {
	it("queues one hidden advisory continuation for a dirty worktree", async () => {
		const harness = createHarness();

		await harness.end();

		assert.equal(harness.sent.length, 1);
		assert.deepEqual(harness.sent[0]?.options, { deliverAs: "followUp" });
		assert.equal(harness.sent[0]?.message.customType, "basecamp-dirty-worktree-reminder");
		assert.equal(harness.sent[0]?.message.display, false);
		assert.match(harness.sent[0]?.message.content ?? "", /commit only coherent changes/);
		assert.match(harness.sent[0]?.message.content ?? "", /unrelated or pre-existing work/);
		assert.match(harness.sent[0]?.message.content ?? "", /substantive task result/);
	});

	it("does not remind across retries or recursively, then resets after settlement", async () => {
		const harness = createHarness();

		await harness.end();
		harness.startMessage("assistant");
		harness.startMessage("custom", "another-extension");
		await harness.end();
		assert.equal(harness.sent.length, 1);

		harness.startReminder();
		await harness.end();
		await harness.end();
		assert.equal(harness.sent.length, 1);

		await harness.settle();
		await harness.end();
		assert.equal(harness.sent.length, 2);
	});

	it("resets reminder suppression if no continuation runs", async () => {
		const harness = createHarness();

		await harness.end();
		await harness.settle();
		await harness.end();

		assert.equal(harness.sent.length, 2);
	});

	it("does nothing when the worktree is clean", async () => {
		const harness = createHarness({ status: { code: 0, stdout: "", stderr: "" } });

		await harness.end();

		assert.deepEqual(harness.sent, []);
	});

	it("does nothing when git status is killed", async () => {
		const harness = createHarness({
			status: { code: 0, stdout: " M src/file.ts\n", stderr: "", killed: true },
		});

		await harness.end();

		assert.deepEqual(harness.sent, []);
	});

	it("uses the teardown-aware variant for dispatched agents", async () => {
		const harness = createHarness({ subagent: true });

		await harness.end();

		assert.equal(harness.sent.length, 1);
		assert.match(harness.sent[0]?.message.content ?? "", /discarded at teardown/);
		assert.match(harness.sent[0]?.message.content ?? "", /only commits on your branch survive/);
		assert.match(harness.sent[0]?.message.content ?? "", /scratch or exploration files/);
	});

	it("does not inspect worktrees for read-only agents", async () => {
		const harness = createHarness({ readOnly: true });

		await harness.end();

		assert.equal(harness.execCalls(), 0);
		assert.deepEqual(harness.sent, []);
	});

	it("does nothing without an active worktree", async () => {
		const harness = createHarness({ state: baseWorkspaceState() });

		await harness.end();

		assert.equal(harness.execCalls(), 0);
		assert.deepEqual(harness.sent, []);
	});

	it("fails open when git status or reminder delivery fails", async () => {
		const gitFailure = createHarness({ execError: new Error("git unavailable") });
		const statusFailure = createHarness({ status: { code: 1, stdout: "", stderr: "not a repo" } });
		const sendOptions: { sendError?: Error } = { sendError: new Error("delivery failed") };
		const sendFailure = createHarness(sendOptions);

		await assert.doesNotReject(() => Promise.resolve(gitFailure.end()));
		await assert.doesNotReject(() => Promise.resolve(statusFailure.end()));
		await assert.doesNotReject(() => Promise.resolve(sendFailure.end()));

		assert.deepEqual(gitFailure.sent, []);
		assert.deepEqual(statusFailure.sent, []);
		assert.deepEqual(sendFailure.sent, []);

		delete sendOptions.sendError;
		await sendFailure.end();
		assert.equal(sendFailure.sent.length, 1);
	});
});
