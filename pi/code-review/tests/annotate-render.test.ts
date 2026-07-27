import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Theme } from "@earendil-works/pi-coding-agent";
import { CommentStore, listItems } from "#code-review/annotate/model.ts";
import {
	findingLocation,
	renderCommentLabel,
	renderFindingCard,
	renderFindingList,
	renderHeader,
} from "#code-review/annotate/render.ts";
import type { Finding } from "#code-review/findings.ts";

const theme = { fg: (_color: string, text: string) => text, bold: (text: string) => text } as unknown as Theme;

function finding(overrides: Partial<Finding> = {}): Finding {
	return {
		dimension: "general",
		severity: "low",
		file: null,
		lineStart: null,
		lineEnd: null,
		title: "Finding title",
		detail: "Finding detail",
		remediation: null,
		...overrides,
	};
}

describe("findingLocation", () => {
	it("falls back to placeholders when the file and line are absent", () => {
		assert.equal(findingLocation(finding()), "(no file):?");
	});

	it("renders file and line when present", () => {
		assert.equal(findingLocation(finding({ file: "src/app.ts", lineStart: 42 })), "src/app.ts:42");
	});
});

describe("renderFindingCard", () => {
	it("summarizes a fileless finding with unknown line and missing remediation", () => {
		const lines = renderFindingCard(
			finding({
				dimension: "security",
				severity: "high",
				title: "Secret can leak",
				detail: "Token is logged.",
			}),
			0,
			3,
			theme,
		);

		assert.ok(lines.includes("Finding 1 of 3"));
		assert.ok(lines.includes("[high] [security]  (no file):?"));
		assert.ok(lines.includes("Secret can leak"));
		assert.ok(lines.includes("Fix: —"));
	});

	it("summarizes a finding with file, line, and remediation text", () => {
		const lines = renderFindingCard(
			finding({
				dimension: "testing",
				severity: "medium",
				file: "src/app.ts",
				lineStart: 42,
				title: "Missing regression coverage",
				remediation: "Add a regression test.",
			}),
			1,
			2,
			theme,
		);

		assert.ok(lines.includes("Finding 2 of 2"));
		assert.ok(lines.includes("[medium] [testing]  src/app.ts:42"));
		assert.ok(lines.includes("Missing regression coverage"));
		assert.ok(lines.includes("Fix: Add a regression test."));
	});

	it("shows the author response body when present", () => {
		const lines = renderFindingCard(finding({ response: "I disagree — this is intentional." }), 0, 1, theme);

		assert.ok(lines.includes("Author response  I disagree — this is intentional."));
	});

	it("shows a placeholder for an absent or whitespace-only author response", () => {
		assert.ok(renderFindingCard(finding(), 0, 1, theme).includes("Author response  —"));
		assert.ok(renderFindingCard(finding({ response: "   " }), 0, 1, theme).includes("Author response  —"));
	});
});

describe("renderFindingList", () => {
	it("marks commented findings and points the cursor at the selection", () => {
		const store = new CommentStore(2);
		store.set(1, "disagree");
		const findings = [
			finding({ severity: "critical", title: "Unsafe write", file: "src/a.ts", lineStart: 7 }),
			finding({ severity: "low", title: "Naming nit" }),
		];

		const lines = renderFindingList(listItems(findings, store), 1, theme);

		assert.equal(lines[0], "  [critical] Unsafe write  src/a.ts:7");
		assert.equal(lines[1], "▸ [low] Naming nit  (no file):?  📝");
	});
});

describe("renderHeader", () => {
	it("reports the finding total and how many carry a comment", () => {
		assert.equal(renderHeader(3, 1, theme), "Code Review  3 findings  ·  1 commented");
		assert.equal(renderHeader(1, 0, theme), "Code Review  1 finding  ·  0 commented");
	});
});

describe("renderCommentLabel", () => {
	it("shows the saved comment under the label when idle", () => {
		assert.equal(renderCommentLabel("known trade-off", false, theme), "Your comment\nknown trade-off");
	});

	it("prompts with the focus key when no comment exists", () => {
		assert.equal(renderCommentLabel("", false, theme), "Your comment  [↓]");
	});

	it("drops the saved text while the editor is focused", () => {
		assert.equal(renderCommentLabel("known trade-off", true, theme), "Your comment");
	});
});
