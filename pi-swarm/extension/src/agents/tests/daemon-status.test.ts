import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	type DaemonStatusInfo,
	previewDaemonMessage,
	publishDaemonStatus,
	renderDaemonStatus,
} from "../daemon/index.ts";

type Theme = (color: string, text: string) => string;

type StatusSetCall = {
	key: string;
	value: string | undefined;
};

describe("daemon status formatting", () => {
	it("sanitizes and truncates unavailable message previews", () => {
		assert.equal(previewDaemonMessage(undefined), null);
		assert.equal(previewDaemonMessage("   \n\t   "), null);
		assert.equal(previewDaemonMessage("  hello\nworld\t!  "), "hello world !");

		const long = "x".repeat(81);
		assert.equal(previewDaemonMessage(long), `${"x".repeat(79)}…`);
	});

	it("formats idle/starting/connected/disconnected/unavailable statuses", () => {
		const fg: Theme = (color, text) => `${color}:${text}`;

		assert.equal(renderDaemonStatus(fg, { kind: "idle" }), "muted:daemon idle");
		assert.equal(renderDaemonStatus(fg, { kind: "starting" }), "warning:daemon … dim:starting");
		assert.equal(renderDaemonStatus(fg, { kind: "connected" }), "success:daemon ✓");
		assert.equal(renderDaemonStatus(fg, { kind: "disconnected" }), "warning:daemon ⚠ dim:disconnected");
		assert.equal(
			renderDaemonStatus(fg, { kind: "unavailable", message: " failed \n with  spaces " }),
			"error:daemon ✗ error:failed   with  spaces",
		);
		assert.equal(renderDaemonStatus(fg, { kind: "unavailable", message: "  " }), "error:daemon ✗ unavailable");
	});
});

describe("publishDaemonStatus", () => {
	it("publishes formatted daemon status through ui.setStatus", () => {
		const calls: StatusSetCall[] = [];
		const fg: Theme = (color, text) => `${color}:${text}`;
		const ctx: any = {
			hasUI: true,
			ui: {
				theme: { fg },
				setStatus: (key: string, value: string | undefined) => {
					calls.push({ key, value });
				},
			},
		};

		const statuses: DaemonStatusInfo[] = [
			{ kind: "starting" },
			{ kind: "connected" },
			{ kind: "disconnected" },
			{ kind: "unavailable", message: "  daemon\terror\nmissing " },
			{ kind: "idle" },
		];
		for (const status of statuses) {
			publishDaemonStatus(ctx, status);
		}

		assert.equal(calls.length, statuses.length);
		for (const call of calls) {
			assert.equal(call.key, "basecamp.daemon");
			assert.ok(typeof call.value === "string");
		}
		assert.equal(calls.at(-1)?.value, "muted:daemon idle");
		assert.match(calls.at(-2)?.value ?? "", /^error:daemon ✗ error:daemon error missing$/);
	});

	it("no-ops when ui is unavailable", () => {
		const ctx: any = {
			hasUI: false,
			ui: {
				setStatus: () => {
					throw new Error("should not run");
				},
			},
		};
		assert.doesNotThrow(() => publishDaemonStatus(ctx, { kind: "connected" }));
	});
});
