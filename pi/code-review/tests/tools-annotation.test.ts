/** `report_findings` behaviour driven by the annotation pane. Non-UI behaviour lives in tools.test.ts. */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { DOWN, ENTER, ESC, SPACE, type } from "./support/pane-driver.ts";
import {
	blockedEnd,
	blockedStart,
	ctxWithPane,
	ctxWithViews,
	finding,
	type ReviewDetails,
	readArtifact,
	registerHarness,
	scope,
	summary,
	withPrimaryScratch,
} from "./support/tool-fixtures.ts";

describe("report_findings annotation", () => {
	it("opens the annotation pane inside a balanced blocked interval", async (t) => {
		withPrimaryScratch(t);
		const { pi, tool } = registerHarness();
		const lifecycle: string[] = [];
		pi.events.emit = (channel, data) => {
			lifecycle.push(`${channel}:${(data as { active: boolean }).active}`);
			pi.emitted.push({ channel, data });
		};
		const ctx = ctxWithViews([{ kind: "submit" }], () => lifecycle.push("annotate"));
		const findings = [finding({ severity: "medium", response: "known trade-off" }), finding({ severity: "low" })];
		const res = await tool.execute("call-1", { scope, summary, findings }, undefined, undefined, ctx);
		const details = res.details as ReviewDetails;

		assert.equal(details.annotated, true);
		assert.deepEqual(lifecycle, ["herdr:blocked:true", "annotate", "herdr:blocked:false"]);
		assert.deepEqual(pi.emitted, [blockedStart, blockedEnd]);
		const persisted = readArtifact(details.artifactPath).findings;
		assert.equal(persisted[0]?.response, "known trade-off");
		assert.deepEqual(
			persisted.map((entry) => entry.reaction),
			[null, null],
		);
	});

	it("carries a typed comment through the pane into the packet at the right index", async (t) => {
		withPrimaryScratch(t);
		const { tool } = registerHarness();
		// Drives the real pane, so the whole seam runs: keystrokes → store → tools.ts → packet.
		const ctx = ctxWithPane([
			(send) => send(DOWN, SPACE),
			(send) => send(DOWN, ...type("agreed, worth a test"), ENTER, ESC),
			(send) => send("s"),
		]);
		const findings = [finding({ severity: "medium" }), finding({ severity: "low" })];
		const res = await tool.execute("call-1", { scope, summary, findings }, undefined, undefined, ctx);
		const details = res.details as ReviewDetails;

		assert.equal(details.annotated, true);
		assert.deepEqual(
			readArtifact(details.artifactPath).findings.map((entry) => entry.reaction),
			[null, "agreed, worth a test"],
		);
	});

	it("keeps the cancelled pane unannotated and clears blocked state", async (t) => {
		withPrimaryScratch(t);
		const { pi, tool } = registerHarness();
		const ctx = ctxWithViews([{ kind: "cancel" }]);
		const res = await tool.execute("call-1", { scope, summary, findings: [finding()] }, undefined, undefined, ctx);
		const details = res.details as ReviewDetails;

		assert.equal(details.annotated, false);
		assert.equal(readArtifact(details.artifactPath).findings[0]?.reaction, null);
		assert.deepEqual(pi.emitted, [blockedStart, blockedEnd]);
	});

	it("discards typed comments when the list is cancelled", async (t) => {
		withPrimaryScratch(t);
		const { tool } = registerHarness();
		const ctx = ctxWithPane([
			(send) => send(SPACE),
			(send) => send(DOWN, ...type("typed then abandoned"), ENTER, ESC),
			(send) => send(ESC),
		]);
		const findings = [finding({ severity: "medium" }), finding({ severity: "low" })];
		const res = await tool.execute("call-1", { scope, summary, findings }, undefined, undefined, ctx);
		const details = res.details as ReviewDetails;

		assert.equal(details.annotated, false);
		assert.deepEqual(
			readArtifact(details.artifactPath).findings.map((entry) => entry.reaction),
			[null, null],
		);
	});

	it("clears blocked state when annotation fails", async (t) => {
		withPrimaryScratch(t);
		const { pi, tool } = registerHarness();
		const ctx = {
			hasUI: true,
			ui: { custom: async () => Promise.reject(new Error("annotation failed")) },
		} as unknown as ExtensionContext;

		await assert.rejects(
			() => tool.execute("call-1", { scope, summary, findings: [finding()] }, undefined, undefined, ctx),
			/annotation failed/,
		);
		assert.deepEqual(pi.emitted, [blockedStart, blockedEnd]);
	});

	it("does not open the pane or mark blocked when there are no findings", async (t) => {
		withPrimaryScratch(t);
		const { pi, tool } = registerHarness();
		const ctx = {
			hasUI: true,
			ui: {
				custom: async () => {
					throw new Error("pane must not open for an empty review");
				},
			},
		} as unknown as ExtensionContext;
		const res = await tool.execute("call-1", { scope, summary, findings: [] }, undefined, undefined, ctx);
		const details = res.details as ReviewDetails;

		assert.equal(details.annotated, false);
		assert.equal(details.decision, "approve");
		assert.deepEqual(pi.emitted, []);
	});
});
