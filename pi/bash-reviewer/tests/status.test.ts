import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { publishReviewerStatus, REVIEWER_STATUS_ID, renderReviewerStatus } from "#bash-reviewer/status.ts";

type ThemeFg = (color: string, text: string) => string;

const fg: ThemeFg = (color, text) => `${color}:${text}`;

describe("reviewer status formatting", () => {
	it("renders on/off with the right colors", () => {
		assert.equal(renderReviewerStatus(fg, false), "success:🛡 on");
		assert.equal(renderReviewerStatus(fg, true), "warning:🛡 off");
	});

	it("keeps theme fg bound to the theme object", () => {
		const theme = {
			prefix: "t",
			fg(this: { prefix: string }, color: string, text: string): string {
				return `${this.prefix}:${color}:${text}`;
			},
		};
		const ctx: any = {
			hasUI: true,
			ui: {
				theme,
				setStatus: () => {},
			},
		};

		// Should not throw — exercises the bind pattern.
		assert.doesNotThrow(() => publishReviewerStatus(ctx, false));
	});
});

describe("publishReviewerStatus", () => {
	it("publishes through ctx.ui.setStatus with the reviewer status id", () => {
		const calls: { key: string; value: string | undefined }[] = [];
		const ctx: any = {
			hasUI: true,
			ui: {
				theme: { fg },
				setStatus: (key: string, value: string | undefined) => calls.push({ key, value }),
			},
		};

		publishReviewerStatus(ctx, false);
		publishReviewerStatus(ctx, true);

		assert.equal(calls.length, 2);
		assert.deepEqual(calls[0], { key: REVIEWER_STATUS_ID, value: "success:🛡 on" });
		assert.deepEqual(calls[1], { key: REVIEWER_STATUS_ID, value: "warning:🛡 off" });
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
		assert.doesNotThrow(() => publishReviewerStatus(ctx, true));
	});
});
