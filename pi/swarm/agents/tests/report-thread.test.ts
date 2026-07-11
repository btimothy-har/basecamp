import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { DaemonConnection } from "../daemon/client.ts";
import type { Frame } from "../daemon/frames/index.ts";
import { PROTOCOL_VERSION } from "../daemon/frames/index.ts";
import { reportThread, type ThreadReport } from "../daemon/report-thread.ts";

function mockConnection(sent: Frame[]): DaemonConnection {
	return {
		send(frame) {
			sent.push(frame);
		},
		on() {
			return () => {};
		},
		onClose() {
			return () => {};
		},
		close() {
			// no-op
		},
	};
}

const REPORT: ThreadReport = {
	node_id: "pi-sess",
	session_id: "pi-sess",
	session_file: "/x/pi-sess.jsonl",
	leaf_id: "e2",
	nodes: [{ id: "e1", parent_id: null, entry_json: "{}" }],
};

describe("reportThread", () => {
	it("wraps the report in a thread_report frame and sends it over the connection", async () => {
		const sent: Frame[] = [];
		await reportThread(
			() => REPORT,
			async () => mockConnection(sent),
		);

		assert.equal(sent.length, 1);
		const frame = sent[0];
		if (frame?.type !== "thread_report") {
			assert.fail("expected a thread_report frame");
		}
		assert.equal(frame.v, PROTOCOL_VERSION);
		assert.equal(frame.node_id, "pi-sess");
		assert.equal(frame.session_id, "pi-sess");
		assert.equal(frame.session_file, "/x/pi-sess.jsonl");
		assert.equal(frame.leaf_id, "e2");
		assert.deepEqual(frame.nodes, REPORT.nodes);
	});

	it("no-ops without building the report when the daemon is unconnected", async () => {
		let built = false;
		await reportThread(
			() => {
				built = true;
				return REPORT;
			},
			async () => null,
		);
		assert.equal(built, false);
	});

	it("resolves the current connection per call (fork → new owner)", async () => {
		const sentA: Frame[] = [];
		const sentB: Frame[] = [];
		let current = mockConnection(sentA);
		await reportThread(
			() => ({ ...REPORT, session_id: "sess-A", node_id: "sess-A" }),
			async () => current,
		);
		current = mockConnection(sentB);
		await reportThread(
			() => ({ ...REPORT, session_id: "sess-B", node_id: "sess-B" }),
			async () => current,
		);

		assert.equal(sentA.length, 1);
		assert.equal(sentB.length, 1);
		const frameA = sentA[0];
		const frameB = sentB[0];
		if (frameA?.type !== "thread_report" || frameB?.type !== "thread_report") {
			assert.fail("expected thread_report frames");
		}
		assert.equal(frameA.session_id, "sess-A");
		assert.equal(frameB.session_id, "sess-B");
	});
});
