import { describe, expect, test } from "bun:test";
import type { Theme } from "@oh-my-pi/pi-coding-agent";
import { CommentStore, listItems } from "../navigator/model.ts";
import {
	findingLocation,
	priorityLabel,
	renderCommentLabel,
	renderFindingCard,
	renderFindingList,
	renderHeader,
	windowRows,
} from "../navigator/render.ts";
import type { IdentifiedReviewFinding, PreparedReview } from "../schema.ts";

const theme = { fg: (_color: string, text: string) => text, bold: (text: string) => text } as unknown as Theme;

function finding(overrides: Partial<IdentifiedReviewFinding> = {}): IdentifiedReviewFinding {
	return {
		id: "finding-1",
		title: "Finding title",
		body: "Finding body",
		priority: 2,
		confidence: 0.8,
		file_path: "src/app.ts",
		line_start: 10,
		line_end: 12,
		...overrides,
	};
}

function review(findings: IdentifiedReviewFinding[]): PreparedReview {
	return {
		scope: "main...HEAD",
		overall_correctness: "incorrect",
		explanation: "Validated findings remain.",
		confidence: 0.9,
		findings,
	};
}

describe("priorityLabel", () => {
	test("renders native P0 through P3 labels", () => {
		expect(priorityLabel(0)).toBe("P0");
		expect(priorityLabel(1)).toBe("P1");
		expect(priorityLabel(2)).toBe("P2");
		expect(priorityLabel(3)).toBe("P3");
	});
});

describe("findingLocation", () => {
	test("renders a range when the finding spans lines", () => {
		expect(findingLocation(finding())).toBe("src/app.ts:10-12");
	});

	test("renders a single line when start and end coincide", () => {
		expect(findingLocation(finding({ line_end: 10 }))).toBe("src/app.ts:10");
	});
});

describe("renderFindingCard", () => {
	test("shows priority, confidence, location, title, and body", () => {
		const lines = renderFindingCard(finding({ priority: 1, confidence: 0.85 }), 1, 3, theme).join("\n");
		expect(lines).toContain("Finding 2 of 3");
		expect(lines).toContain("[P1]");
		expect(lines).toContain("85% confidence");
		expect(lines).toContain("src/app.ts:10-12");
		expect(lines).toContain("Finding title");
		expect(lines).toContain("Finding body");
	});

	test("omits legacy dimensions, remediation, and author response sections", () => {
		const lines = renderFindingCard(finding(), 0, 1, theme).join("\n");
		expect(lines).not.toContain("Fix:");
		expect(lines).not.toContain("Author response");
		expect(lines).not.toContain("[general]");
	});
});

describe("renderFindingList", () => {
	test("marks the selected row and the commented finding", () => {
		const findings = [finding(), finding({ id: "finding-2", title: "Second", priority: 0 })];
		const store = new CommentStore(findings);
		store.set("finding-2", "noted");
		const lines = renderFindingList(listItems(findings, store), 0, theme);
		expect(lines[0]).toContain("▸");
		expect(lines[1]).not.toContain("▸");
		expect(lines[1]).toContain("[P0]");
		expect(lines[1]).toContain("[commented]");
		expect(lines[0]).not.toContain("[commented]");
	});

	test("keeps the selected finding in a bounded list window", () => {
		const findings = Array.from({ length: 40 }, (_unused, index) =>
			finding({ id: `finding-${index + 1}`, title: `Finding ${index + 1}` }),
		);
		const lines = renderFindingList(listItems(findings, new CommentStore(findings)), 30, theme, 8);

		expect(lines.length).toBeLessThanOrEqual(8);
		expect(lines.join("\n")).toContain("▸ [P2] Finding 31");
		expect(lines[0]).toContain("earlier");
		expect(lines.at(-1)).toContain("more");
	});
});

describe("windowRows", () => {
	test("bounds long card content and follows the requested offset", () => {
		const rows = Array.from({ length: 50 }, (_unused, index) => `line ${index}`);
		const top = windowRows(rows, 0, 10, theme);
		const lower = windowRows(rows, 20, 10, theme);

		expect(top.lines.length).toBeLessThanOrEqual(10);
		expect(top.lines.join("\n")).toContain("line 0");
		expect(lower.lines.join("\n")).toContain("line 20");
		expect(lower.lines[0]).toContain("earlier");
	});
});

describe("renderHeader", () => {
	test("shows scope, verdict, priority counts, and comments", () => {
		const findings = [finding({ priority: 0 }), finding({ id: "finding-2", priority: 2 })];
		const header = renderHeader(review(findings), 1, theme);
		expect(header).toContain("main...HEAD");
		expect(header).toContain("Incorrect  ·  2 findings  ·  1 commented");
		expect(header).toContain("P0 1   P1 0   P2 1   P3 0");
	});
});

describe("renderCommentLabel", () => {
	test("points at the box when empty, echoes the comment when saved", () => {
		expect(renderCommentLabel("", false, theme)).toContain("[↓]");
		expect(renderCommentLabel("saved", false, theme)).toContain("saved");
		expect(renderCommentLabel("", true, theme)).not.toContain("[↓]");
	});
});
