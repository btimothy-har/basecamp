import { describe, expect, test } from "bun:test";
import { navigateReviewFindings } from "../navigator/index.ts";
import type { IdentifiedReviewFinding, PreparedReview } from "../schema.ts";
import {
	BACKSPACE,
	bracketedPaste,
	DOWN,
	ENTER,
	ESC,
	navigatorHarness as harness,
	LEFT,
	PAGE_DOWN,
	RIGHT,
	SPACE,
	type,
} from "./support/navigator-driver.ts";

function finding(overrides: Partial<IdentifiedReviewFinding> = {}): IdentifiedReviewFinding {
	return {
		id: "finding-1",
		title: "Finding title",
		body: "Finding body",
		recommendation: "Apply the focused fix.",
		priority: 2,
		confidence: 0.8,
		file_path: "src/app.ts",
		line_start: 10,
		line_end: 12,
		...overrides,
	};
}

const twoFindings = [finding(), finding({ id: "finding-2", title: "second" })];

function review(findings: IdentifiedReviewFinding[] = twoFindings): PreparedReview {
	return {
		scope: "main...HEAD",
		overall_correctness: findings.length === 0 ? "correct" : "incorrect",
		explanation: findings.length === 0 ? "No validated findings." : "Validated findings remain.",
		recommendation: findings.length === 0 ? "Merge after CI passes." : "Fix the validated findings before merging.",
		confidence: 0.9,
		findings,
	};
}

describe("navigateReviewFindings", () => {
	test("keeps a comment saved with Enter", async () => {
		const ui = harness([
			(send) => send(SPACE),
			(send) => send(DOWN, ...type("looks intentional"), ENTER, ESC),
			(send) => send("s"),
		]);

		const result = await navigateReviewFindings(ui, review());

		expect(result).toEqual({ cancelled: false, comments: { "finding-1": "looks intentional" } });
	});

	test("keeps a comment saved with Esc", async () => {
		const ui = harness([
			(send) => send(SPACE),
			(send) => send(DOWN, ...type("escaped out"), ESC, ESC),
			(send) => send("s"),
		]);

		const result = await navigateReviewFindings(ui, review());

		expect(result).toEqual({ cancelled: false, comments: { "finding-1": "escaped out" } });
	});

	test("keeps comments keyed to their finding across navigation", async () => {
		let idleView = "";
		let reopenedEditor = "";
		const ui = harness([
			(send) => send(SPACE),
			(send, render) => {
				send(DOWN, ...type("first pass"), ENTER);
				send(RIGHT, DOWN, ...type("other"), ENTER);
				send(LEFT);
				idleView = render();
				send(DOWN);
				reopenedEditor = render();
				send(ESC, ESC);
			},
			(send) => send("s"),
		]);

		const result = await navigateReviewFindings(ui, review());

		expect(idleView).toContain("first pass");
		expect(reopenedEditor).toContain("first pass");
		expect(result.comments).toEqual({ "finding-1": "first pass", "finding-2": "other" });
	});

	test("marks commented findings in the list", async () => {
		let listView = "";
		const ui = harness([
			(send) => send(SPACE),
			(send) => send(DOWN, ...type("noted"), ENTER, ESC),
			(send, render) => {
				listView = render();
				send("s");
			},
		]);

		await navigateReviewFindings(ui, review());

		expect(listView).toContain("1 commented");
		expect(listView).toContain("Finding title");
		expect(listView).toContain("[commented]");
	});

	test("keeps the overall recommendation visible in a short terminal", async () => {
		let listView = "";
		const ui = harness([
			(send, render, _paste, resize) => {
				resize?.(14);
				listView = render();
				send("s");
			},
		]);

		await navigateReviewFindings(ui, review());

		expect(listView.split("\n").length).toBeLessThanOrEqual(14);
		expect(listView).toContain("Overall recommendation");
		expect(listView).toContain("Fix the validated findings before merging.");
		expect(listView).toContain("Finding title");
	});

	test("clips long review guidance while keeping findings visible after resize", async () => {
		let listView = "";
		const guidance = Array.from({ length: 120 }, (_unused, index) => `recommendation-${index}`).join(" ");
		const ui = harness([
			(send, render, _paste, resize) => {
				resize?.(20);
				listView = render();
				send("s");
				resize?.(40);
			},
		]);

		await navigateReviewFindings(ui, { ...review(), explanation: guidance, recommendation: guidance });

		expect(listView.split("\n").length).toBeLessThanOrEqual(20);
		expect(listView).toContain("Overall recommendation");
		expect(listView).toContain("Finding title");
		expect(listView).toContain("…");
		expect(listView).not.toContain("more line");
	});

	test("does not open the comment box on Enter from the card", async () => {
		const ui = harness([
			(send) => send(SPACE),
			// Enter must be inert here; the characters that follow would otherwise become a comment.
			(send) => send(ENTER, ...type("not a comment"), ESC),
			(send) => send("s"),
		]);

		const result = await navigateReviewFindings(ui, review());

		expect(result.comments).toEqual({});
	});

	test("clears a comment when the box is emptied", async () => {
		const ui = harness([
			(send) => send(SPACE),
			(send) => send(DOWN, ...type("temporary"), ENTER, DOWN, ...Array(9).fill(BACKSPACE), ENTER, ESC),
			(send) => send("s"),
		]);

		const result = await navigateReviewFindings(ui, review());

		expect(result.comments).toEqual({});
	});

	test("saves the whole of a large paste on both the Enter and the Esc path", async () => {
		const paste = bracketedPaste(12);
		const ui = harness([
			(send) => send(SPACE),
			(send) => {
				send(DOWN, paste.keys, ENTER);
				send(RIGHT, DOWN, paste.keys, ESC);
				send(ESC);
			},
			(send) => send("s"),
		]);

		const result = await navigateReviewFindings(ui, review());

		expect(result.comments).toEqual({ "finding-1": paste.text, "finding-2": paste.text });
	});

	test("keeps a pasted comment intact when the finding is revisited", async () => {
		const paste = bracketedPaste(12);
		const ui = harness([
			(send) => send(SPACE),
			(send) => send(DOWN, paste.keys, ESC, DOWN, ESC, ESC),
			(send) => send("s"),
		]);

		const result = await navigateReviewFindings(ui, review());

		// Re-entering the box reseeds it from the store, which clears the Editor's paste map — the
		// stored text must already be the real content or it becomes an orphaned marker forever.
		expect(result.comments).toEqual({ "finding-1": paste.text });
	});

	test("routes enhanced paste into the focused comment editor", async () => {
		const ui = harness([
			(send) => send(SPACE),
			(send, _render, paste) => {
				send(DOWN);
				paste?.("evidence from clipboard");
				send(ENTER, ESC);
			},
			(send) => send("s"),
		]);

		const result = await navigateReviewFindings(ui, review());

		expect(result.comments).toEqual({ "finding-1": "evidence from clipboard" });
	});

	test("keeps long finding lists centered on the selection after a resize", async () => {
		const findings = Array.from({ length: 40 }, (_unused, index) =>
			finding({ id: `finding-${index + 1}`, title: `Finding ${index + 1}` }),
		);
		let listView = "";
		const ui = harness([
			(send, render, _paste, resize) => {
				send(...Array(35).fill(DOWN));
				resize?.(20);
				listView = render();
				send("s");
				resize?.(40);
			},
		]);

		await navigateReviewFindings(ui, review(findings));

		expect(listView).toContain("▸ [P2] Finding 36");
		expect(listView.split("\n").length).toBeLessThanOrEqual(20);
	});

	test("scrolls long finding cards without clipping the beginning permanently", async () => {
		const body = Array.from({ length: 60 }, (_unused, index) => `evidence line ${index}`).join("\n");
		let topView = "";
		let lowerView = "";
		let bottomView = "";
		const ui = harness([
			(send) => send(SPACE),
			(send, render) => {
				topView = render();
				send(PAGE_DOWN);
				lowerView = render();
				send(PAGE_DOWN);
				bottomView = render();
				send(ESC);
			},
			(send) => send("s"),
		]);

		await navigateReviewFindings(ui, review([finding({ body })]));

		expect(topView).toContain("evidence line 0");
		expect(lowerView).toContain("evidence line 30");
		expect(lowerView).not.toContain("evidence line 0");
		expect(bottomView).toContain("Recommendation");
		expect(bottomView).toContain("Apply the focused fix.");
	});

	test("places the comment box under the label even when a finding quotes it", async () => {
		const quoting = finding({
			title: "Stale doc comment",
			body: "Your comment on line 5 no longer matches the code.",
		});
		let editing = "";
		const ui = harness([
			(send) => send(SPACE),
			(send, render) => {
				send(DOWN, ...type("ZZMARKER"));
				editing = render();
				send(ESC, ESC);
			},
			(send) => send("s"),
		]);

		await navigateReviewFindings(ui, review([quoting, finding({ id: "finding-2", title: "second" })]));

		const lines = editing.split("\n");
		const lastLabel = lines.map((line) => line.includes("Your comment")).lastIndexOf(true);
		const box = lines.findIndex((line) => line.includes("ZZMARKER"));
		expect(lastLabel >= 0 && box >= 0).toBe(true);
		expect(box > lastLabel).toBe(true);
	});

	test("discards every comment when the list is cancelled", async () => {
		const ui = harness([
			(send) => send(SPACE),
			(send) => send(DOWN, ...type("typed then abandoned"), ENTER, ESC),
			(send) => send(ESC),
		]);

		const result = await navigateReviewFindings(ui, review());

		expect(result).toEqual({ cancelled: true, comments: {} });
	});

	test("returns immediately without opening a view when there are no findings", async () => {
		const result = await navigateReviewFindings(harness([]), review([]));

		expect(result).toEqual({ cancelled: false, comments: {} });
	});
});
