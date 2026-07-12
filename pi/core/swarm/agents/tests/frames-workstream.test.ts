import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { decodeFrame, FRAME_TYPES, type Frame, PROTOCOL_VERSION } from "../../../hub/protocol/index.ts";
import { createDaemonClient } from "../client.ts";
import { MockConnection } from "./harness.ts";

const NEW_FRAME_TYPES = [
	"create_workstream",
	"create_workstream_ack",
	"attach_workstream_agent",
	"attach_workstream_agent_ack",
	"update_workstream",
	"update_workstream_ack",
] as const;

describe("daemon workstream frames", () => {
	it("FRAME_TYPES contains the six new workstream types", () => {
		for (const type of NEW_FRAME_TYPES) {
			assert.ok(FRAME_TYPES.includes(type), `FRAME_TYPES missing ${type}`);
		}
	});

	it("decodeFrame accepts create_workstream at v19 and rejects at v18", () => {
		const frame = {
			type: "create_workstream",
			v: PROTOCOL_VERSION,
			request_id: "req-1",
			workstream_id: "ws-1",
			slug: "alpha",
			label: "Alpha",
			brief: "Do the thing",
			source_dossier_path: "/tmp/dossier.md",
			constraints: null,
			source_repo_page_path: null,
		};
		assert.equal(decodeFrame(JSON.stringify(frame)).type, "create_workstream");

		const stale = { ...frame, v: 18 };
		assert.throws(() => decodeFrame(JSON.stringify(stale)), /Protocol version mismatch/);
	});

	it("decodeFrame accepts create_workstream_ack at v19 and rejects at v18", () => {
		const frame = {
			type: "create_workstream_ack",
			v: PROTOCOL_VERSION,
			request_id: "req-1",
			status: "created",
			workstream_id: "ws-1",
			slug: "alpha",
			error: null,
		};
		assert.equal(decodeFrame(JSON.stringify(frame)).type, "create_workstream_ack");

		const stale = { ...frame, v: 18 };
		assert.throws(() => decodeFrame(JSON.stringify(stale)), /Protocol version mismatch/);
	});

	it("decodeFrame accepts attach_workstream_agent at v19 and rejects at v18", () => {
		const frame = {
			type: "attach_workstream_agent",
			v: PROTOCOL_VERSION,
			request_id: "req-2",
			workstream: "alpha",
			repo: "org/repo",
			worktree_label: "wt-1",
			status: "attached",
			error: null,
		};
		assert.equal(decodeFrame(JSON.stringify(frame)).type, "attach_workstream_agent");

		const stale = { ...frame, v: 18 };
		assert.throws(() => decodeFrame(JSON.stringify(stale)), /Protocol version mismatch/);
	});

	it("decodeFrame accepts attach_workstream_agent_ack at v19 and rejects at v18", () => {
		const frame = {
			type: "attach_workstream_agent_ack",
			v: PROTOCOL_VERSION,
			request_id: "req-2",
			status: "attached",
			error: null,
		};
		assert.equal(decodeFrame(JSON.stringify(frame)).type, "attach_workstream_agent_ack");

		const stale = { ...frame, v: 18 };
		assert.throws(() => decodeFrame(JSON.stringify(stale)), /Protocol version mismatch/);
	});

	it("decodeFrame accepts update_workstream at v19 and rejects at v18", () => {
		const frame = {
			type: "update_workstream",
			v: PROTOCOL_VERSION,
			request_id: "req-3",
			workstream: "alpha",
			status: "closed",
		};
		assert.equal(decodeFrame(JSON.stringify(frame)).type, "update_workstream");

		const stale = { ...frame, v: 18 };
		assert.throws(() => decodeFrame(JSON.stringify(stale)), /Protocol version mismatch/);
	});

	it("decodeFrame accepts update_workstream_ack at v19 and rejects at v18", () => {
		const frame = {
			type: "update_workstream_ack",
			v: PROTOCOL_VERSION,
			request_id: "req-3",
			status: "updated",
			error: null,
		};
		assert.equal(decodeFrame(JSON.stringify(frame)).type, "update_workstream_ack");

		const stale = { ...frame, v: 18 };
		assert.throws(() => decodeFrame(JSON.stringify(stale)), /Protocol version mismatch/);
	});
});

describe("daemon workstream client methods", () => {
	it("createWorkstream sends the correctly-shaped frame and resolves with the ack payload", async () => {
		const connection = new MockConnection();
		const client = createDaemonClient(connection);

		const promise = client.createWorkstream({
			workstreamId: "ws-1",
			slug: "alpha",
			label: "Alpha",
			brief: "Do the thing",
			sourceDossierPath: "/tmp/dossier.md",
			constraints: "stay small",
			sourceRepoPagePath: "/tmp/page.md",
		});
		await new Promise((resolve) => setImmediate(resolve));

		const outbound = connection.sent[0] as Extract<Frame, { type: "create_workstream" }>;
		assert.equal(outbound.type, "create_workstream");
		assert.equal(outbound.v, PROTOCOL_VERSION);
		assert.equal(typeof outbound.request_id, "string");
		assert.equal(outbound.workstream_id, "ws-1");
		assert.equal(outbound.slug, "alpha");
		assert.equal(outbound.label, "Alpha");
		assert.equal(outbound.brief, "Do the thing");
		assert.equal(outbound.source_dossier_path, "/tmp/dossier.md");
		assert.equal(outbound.constraints, "stay small");
		assert.equal(outbound.source_repo_page_path, "/tmp/page.md");

		connection.emit({
			type: "create_workstream_ack",
			v: PROTOCOL_VERSION,
			request_id: outbound.request_id,
			status: "created",
			workstream_id: "ws-1",
			slug: "alpha",
			error: null,
		});

		assert.deepEqual(await promise, {
			status: "created",
			workstream_id: "ws-1",
			slug: "alpha",
			error: null,
		});
	});

	it("createWorkstream maps undefined optional fields to null on the wire", async () => {
		const connection = new MockConnection();
		const client = createDaemonClient(connection);

		const promise = client.createWorkstream({
			workstreamId: "ws-2",
			slug: "beta",
			label: "Beta",
			brief: "Another thing",
			sourceDossierPath: "/tmp/dossier2.md",
		});
		await new Promise((resolve) => setImmediate(resolve));

		const outbound = connection.sent[0] as Extract<Frame, { type: "create_workstream" }>;
		assert.equal(outbound.constraints, null);
		assert.equal(outbound.source_repo_page_path, null);

		connection.emit({
			type: "create_workstream_ack",
			v: PROTOCOL_VERSION,
			request_id: outbound.request_id,
			status: "slug_conflict",
			workstream_id: null,
			slug: null,
			error: "slug taken",
		});

		assert.deepEqual(await promise, {
			status: "slug_conflict",
			workstream_id: null,
			slug: null,
			error: "slug taken",
		});
	});

	it("attachWorkstreamAgent sends the correctly-shaped frame and resolves with the ack payload", async () => {
		const connection = new MockConnection();
		const client = createDaemonClient(connection);

		const promise = client.attachWorkstreamAgent({
			workstream: "alpha",
			repo: "org/repo",
			worktreeLabel: "wt-1",
			status: "attached",
			error: null,
		});
		await new Promise((resolve) => setImmediate(resolve));

		const outbound = connection.sent[0] as Extract<Frame, { type: "attach_workstream_agent" }>;
		assert.equal(outbound.type, "attach_workstream_agent");
		assert.equal(outbound.v, PROTOCOL_VERSION);
		assert.equal(typeof outbound.request_id, "string");
		assert.equal(outbound.workstream, "alpha");
		assert.equal(outbound.repo, "org/repo");
		assert.equal(outbound.worktree_label, "wt-1");
		assert.equal(outbound.status, "attached");
		assert.equal(outbound.error, null);

		connection.emit({
			type: "attach_workstream_agent_ack",
			v: PROTOCOL_VERSION,
			request_id: outbound.request_id,
			status: "attached",
			error: null,
		});

		assert.deepEqual(await promise, { status: "attached", error: null });
	});

	it("updateWorkstream sends the correctly-shaped frame and resolves with the ack payload", async () => {
		const connection = new MockConnection();
		const client = createDaemonClient(connection);

		const promise = client.updateWorkstream({ workstream: "alpha", status: "closed" });
		await new Promise((resolve) => setImmediate(resolve));

		const outbound = connection.sent[0] as Extract<Frame, { type: "update_workstream" }>;
		assert.equal(outbound.type, "update_workstream");
		assert.equal(outbound.v, PROTOCOL_VERSION);
		assert.equal(typeof outbound.request_id, "string");
		assert.equal(outbound.workstream, "alpha");
		assert.equal(outbound.status, "closed");

		connection.emit({
			type: "update_workstream_ack",
			v: PROTOCOL_VERSION,
			request_id: outbound.request_id,
			status: "updated",
			error: null,
		});

		assert.deepEqual(await promise, { status: "updated", error: null });
	});
});
