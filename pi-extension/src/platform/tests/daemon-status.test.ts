import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";
import {
	getDaemonStatus,
	onDaemonStatusChange,
	resetDaemonStatusForTesting,
	setDaemonStatus,
} from "../daemon-status.ts";

describe("daemon status platform store", () => {
	beforeEach(() => resetDaemonStatusForTesting());

	it("starts idle", () => {
		assert.deepEqual(getDaemonStatus(), { kind: "idle" });
	});

	it("normalizes empty messages", () => {
		setDaemonStatus({ kind: "unavailable", message: "  " });

		assert.deepEqual(getDaemonStatus(), { kind: "unavailable" });
	});

	it("notifies subscribers only when status changes", () => {
		const seen: unknown[] = [];
		const unsubscribe = onDaemonStatusChange((status) => seen.push(status));

		setDaemonStatus({ kind: "starting" });
		setDaemonStatus({ kind: "starting" });
		setDaemonStatus({ kind: "unavailable", message: "boom" });
		unsubscribe();
		setDaemonStatus({ kind: "connected" });

		assert.deepEqual(seen, [{ kind: "starting" }, { kind: "unavailable", message: "boom" }]);
		assert.deepEqual(getDaemonStatus(), { kind: "connected" });
	});
});
