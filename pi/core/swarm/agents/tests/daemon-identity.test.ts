import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { deriveDaemonIdentity } from "../../../hub/identity.ts";
import { installDaemonToolTestHooks } from "./harness.ts";

describe("deriveDaemonIdentity", () => {
	installDaemonToolTestHooks();

	it("deriveDaemonIdentity prefers BASECAMP_AGENT_TITLE with short session-id suffix", () => {
		const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		const priorAgentId = process.env.BASECAMP_AGENT_ID;
		const priorAgentTitle = process.env.BASECAMP_AGENT_TITLE;
		const priorAgentHandle = process.env.BASECAMP_AGENT_HANDLE;

		process.env.BASECAMP_AGENT_DEPTH = "1";
		process.env.BASECAMP_AGENT_ID = "agent-xyz";
		process.env.BASECAMP_AGENT_TITLE = "(scout) do thing";
		delete process.env.BASECAMP_AGENT_HANDLE;

		try {
			const identity = deriveDaemonIdentity({
				sessionManager: { getSessionId: () => "0199-aaaa-bbbb-cccc-ddddeeee9f3c" },
			} as any);
			assert.equal(identity.session_name, "(scout) do thing [9f3c]");
			assert.match(identity.agent_handle, /^[a-z]+-[a-z]+-[0-9a-f]{6}$/);
		} finally {
			if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
			if (priorAgentId === undefined) delete process.env.BASECAMP_AGENT_ID;
			else process.env.BASECAMP_AGENT_ID = priorAgentId;
			if (priorAgentTitle === undefined) delete process.env.BASECAMP_AGENT_TITLE;
			else process.env.BASECAMP_AGENT_TITLE = priorAgentTitle;
			if (priorAgentHandle === undefined) delete process.env.BASECAMP_AGENT_HANDLE;
			else process.env.BASECAMP_AGENT_HANDLE = priorAgentHandle;
		}
	});

	it("deriveDaemonIdentity falls back to BASECAMP_SESSION_NAME or node id when BASECAMP_AGENT_TITLE is unset", () => {
		const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		const priorAgentId = process.env.BASECAMP_AGENT_ID;
		const priorAgentTitle = process.env.BASECAMP_AGENT_TITLE;
		const priorAgentHandle = process.env.BASECAMP_AGENT_HANDLE;
		const priorSessionName = process.env.BASECAMP_SESSION_NAME;

		process.env.BASECAMP_AGENT_DEPTH = "1";
		process.env.BASECAMP_AGENT_ID = "agent-fallback";
		delete process.env.BASECAMP_AGENT_TITLE;
		delete process.env.BASECAMP_AGENT_HANDLE;

		try {
			const identity = deriveDaemonIdentity({
				sessionManager: { getSessionId: () => "session-id" },
			} as any);
			assert.equal(identity.session_name, process.env.BASECAMP_SESSION_NAME ?? "agent-fallback");
			assert.match(identity.agent_handle, /^[a-z]+-[a-z]+-[0-9a-f]{6}$/);
		} finally {
			if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
			if (priorAgentId === undefined) delete process.env.BASECAMP_AGENT_ID;
			else process.env.BASECAMP_AGENT_ID = priorAgentId;
			if (priorAgentTitle === undefined) delete process.env.BASECAMP_AGENT_TITLE;
			else process.env.BASECAMP_AGENT_TITLE = priorAgentTitle;
			if (priorAgentHandle === undefined) delete process.env.BASECAMP_AGENT_HANDLE;
			else process.env.BASECAMP_AGENT_HANDLE = priorAgentHandle;
			if (priorSessionName === undefined) delete process.env.BASECAMP_SESSION_NAME;
			else process.env.BASECAMP_SESSION_NAME = priorSessionName;
		}
	});

	it("deriveDaemonIdentity builds a stable canonical handle for top-level sessions", () => {
		const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		const priorAgentId = process.env.BASECAMP_AGENT_ID;
		const priorAgentHandle = process.env.BASECAMP_AGENT_HANDLE;

		delete process.env.BASECAMP_AGENT_DEPTH;
		delete process.env.BASECAMP_AGENT_ID;
		delete process.env.BASECAMP_AGENT_HANDLE;

		try {
			const ctx = { sessionManager: { getSessionId: () => "session-stable-123" } } as any;
			const first = deriveDaemonIdentity(ctx);
			const second = deriveDaemonIdentity(ctx);
			assert.equal(first.role, "agent");
			assert.equal(first.agent_handle, second.agent_handle);
			assert.match(first.agent_handle, /^[a-z]+-[a-z]+-[0-9a-f]{6}$/);
			assert.notEqual(first.agent_handle, "session-stable-123");
		} finally {
			if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
			if (priorAgentId === undefined) delete process.env.BASECAMP_AGENT_ID;
			else process.env.BASECAMP_AGENT_ID = priorAgentId;
			if (priorAgentHandle === undefined) delete process.env.BASECAMP_AGENT_HANDLE;
			else process.env.BASECAMP_AGENT_HANDLE = priorAgentHandle;
		}
	});

	it("deriveDaemonIdentity ignores BASECAMP_AGENT_HANDLE for top-level sessions", () => {
		const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		const priorAgentId = process.env.BASECAMP_AGENT_ID;
		const priorAgentHandle = process.env.BASECAMP_AGENT_HANDLE;

		delete process.env.BASECAMP_AGENT_DEPTH;
		delete process.env.BASECAMP_AGENT_ID;
		process.env.BASECAMP_AGENT_HANDLE = "quiet-badger-3dc450";

		try {
			const ctx = { sessionManager: { getSessionId: () => "session-stable-123" } } as any;
			const first = deriveDaemonIdentity(ctx);
			const second = deriveDaemonIdentity(ctx);
			assert.equal(first.role, "agent");
			assert.notEqual(first.agent_handle, "quiet-badger-3dc450");
			assert.equal(first.agent_handle, second.agent_handle);
			assert.match(first.agent_handle, /^[a-z]+-[a-z]+-[0-9a-f]{6}$/);
		} finally {
			if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
			if (priorAgentId === undefined) delete process.env.BASECAMP_AGENT_ID;
			else process.env.BASECAMP_AGENT_ID = priorAgentId;
			if (priorAgentHandle === undefined) delete process.env.BASECAMP_AGENT_HANDLE;
			else process.env.BASECAMP_AGENT_HANDLE = priorAgentHandle;
		}
	});

	it("deriveDaemonIdentity includes session file when available", () => {
		const ctx = {
			sessionManager: {
				getSessionId: () => "session-with-file",
				getSessionFile: () => "/tmp/pi-session.jsonl",
			},
		} as any;

		const identity = deriveDaemonIdentity(ctx);

		assert.equal(identity.session_file, "/tmp/pi-session.jsonl");
	});

	it("deriveDaemonIdentity prefers BASECAMP_AGENT_HANDLE for spawned agents", () => {
		const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		const priorAgentId = process.env.BASECAMP_AGENT_ID;
		const priorAgentHandle = process.env.BASECAMP_AGENT_HANDLE;

		process.env.BASECAMP_AGENT_DEPTH = "1";
		process.env.BASECAMP_AGENT_ID = "agent-spawned";
		process.env.BASECAMP_USER_FACING = "0";
		process.env.BASECAMP_AGENT_HANDLE = "quiet-badger-3dc450";

		try {
			const identity = deriveDaemonIdentity({ sessionManager: { getSessionId: () => "child-session" } } as any);
			assert.equal(identity.role, "worker");
			assert.equal(identity.node_id, "agent-spawned");
			assert.equal(identity.agent_handle, "quiet-badger-3dc450");
		} finally {
			if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
			if (priorAgentId === undefined) delete process.env.BASECAMP_AGENT_ID;
			else process.env.BASECAMP_AGENT_ID = priorAgentId;
			if (priorAgentHandle === undefined) delete process.env.BASECAMP_AGENT_HANDLE;
			else process.env.BASECAMP_AGENT_HANDLE = priorAgentHandle;
		}
	});
});
