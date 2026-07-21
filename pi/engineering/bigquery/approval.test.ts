import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { buildScanApprovalMetadata, evaluateScanApproval } from "./approval.ts";
import { emptyDryRun } from "./job-summary.ts";
import type { BqQueryDetails, BqScanApprovalMode } from "./params.ts";

interface EmittedEvent {
	channel: string;
	data: unknown;
}

class FakePi {
	readonly emitted: EmittedEvent[] = [];
	readonly events = {
		emit: (channel: string, data: unknown) => {
			this.emitted.push({ channel, data });
		},
		on: () => () => {},
	};
}

const blockedStart: EmittedEvent = {
	channel: "herdr:blocked",
	data: { active: true, label: "Waiting for BigQuery approval" },
};
const blockedEnd: EmittedEvent = { channel: "herdr:blocked", data: { active: false } };

function details(mode: BqScanApprovalMode = "interactive_approval"): BqQueryDetails {
	const estimatedBytes = mode === "interactive_approval" ? "1000000000001" : "5000000000001";
	return {
		description: "Test approval",
		sqlPath: "/tmp/pi/query.sql",
		outputPath: "/tmp/pi/query.csv",
		outputFormat: "csv",
		maxRows: 100,
		projectId: null,
		location: null,
		jobId: "job-1",
		outputBytes: null,
		rowCount: null,
		diagnosticPath: null,
		dryRun: { ...emptyDryRun(), ran: true, jobId: "dry-run-1", estimatedBytes, statementType: "SELECT" },
		approval: buildScanApprovalMetadata(estimatedBytes, "SELECT", mode),
		job: null,
	};
}

function context(confirm: () => Promise<boolean>, hasUI = true): ExtensionContext {
	return { hasUI, ui: { confirm } } as unknown as ExtensionContext;
}

describe("BigQuery Herdr approval state", () => {
	it("brackets approved and declined confirmations", async () => {
		for (const approved of [true, false]) {
			const pi = new FakePi();
			const queryDetails = details();
			const result = await evaluateScanApproval(
				pi as unknown as ExtensionAPI,
				queryDetails,
				context(async () => approved),
				undefined,
				false,
			);

			assert.deepEqual(pi.emitted, [blockedStart, blockedEnd]);
			assert.equal(queryDetails.approval.approved, approved);
			assert.equal(result === null, approved);
		}
	});

	it("clears blocked state on aborts and other confirmation errors", async () => {
		for (const error of [new DOMException("aborted", "AbortError"), new Error("confirmation failed")]) {
			const pi = new FakePi();
			await assert.rejects(
				() =>
					evaluateScanApproval(
						pi as unknown as ExtensionAPI,
						details(),
						context(async () => {
							throw error;
						}),
						undefined,
						false,
					),
				error,
			);
			assert.deepEqual(pi.emitted, [blockedStart, blockedEnd]);
		}
	});

	it("does not report blocked state for the no-UI soft lock", async () => {
		const pi = new FakePi();
		const result = await evaluateScanApproval(
			pi as unknown as ExtensionAPI,
			details("no_ui_soft_lock"),
			context(async () => {
				throw new Error("confirm should not run");
			}, false),
			undefined,
			false,
		);

		assert.equal(result?.isError, true);
		assert.deepEqual(pi.emitted, []);
	});
});
