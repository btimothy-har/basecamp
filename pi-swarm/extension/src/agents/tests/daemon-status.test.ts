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

		assert.equal(renderDaemonStatus(fg, { kind: "idle" }), "muted:swarm idle");
		assert.equal(renderDaemonStatus(fg, { kind: "starting" }), "warning:swarm … dim:starting");
		assert.equal(renderDaemonStatus(fg, { kind: "connected" }), "success:swarm ✓");
		assert.equal(renderDaemonStatus(fg, { kind: "disconnected" }), "warning:swarm ⚠ dim:disconnected");
		assert.equal(
			renderDaemonStatus(fg, { kind: "unavailable", message: " failed \n with  spaces " }),
			"error:swarm ✗ error:failed   with  spaces",
		);
		assert.equal(renderDaemonStatus(fg, { kind: "unavailable", message: "  " }), "error:swarm ✗ unavailable");
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
		assert.equal(calls.at(-1)?.value, "muted:swarm idle");
		assert.match(calls.at(-2)?.value ?? "", /^error:swarm ✗ error:daemon error missing$/);
	});

	it("keeps theme fg bound to the theme object", () => {
		const calls: StatusSetCall[] = [];
		const theme = {
			prefix: "theme",
			fg(this: { prefix: string }, color: string, text: string): string {
				return `${this.prefix}:${color}:${text}`;
			},
		};
		const ctx: any = {
			hasUI: true,
			ui: {
				theme,
				setStatus: (key: string, value: string | undefined) => {
					calls.push({ key, value });
				},
			},
		};

		publishDaemonStatus(ctx, { kind: "connected" });

		assert.deepEqual(calls, [{ key: "basecamp.daemon", value: "theme:success:swarm ✓" }]);
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
