import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { annotateFindings } from "#code-review/annotate/index.ts";
import type { Finding } from "#code-review/findings.ts";
import {
	BACKSPACE,
	bracketedPaste,
	DOWN,
	ENTER,
	ESC,
	paneHarness as harness,
	LEFT,
	RIGHT,
	SPACE,
	type,
} from "./support/pane-driver.ts";

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

const twoFindings = [finding({ title: "first" }), finding({ title: "second" })];

describe("annotateFindings", () => {
	it("keeps a comment saved with Enter", async () => {
		const ui = harness([
			(send) => send(SPACE),
			(send) => send(DOWN, ...type("looks intentional"), ENTER, ESC),
			(send) => send("s"),
		]);

		const result = await annotateFindings(ui, twoFindings);

		assert.deepEqual(result, { cancelled: false, reactions: ["looks intentional", null] });
	});

	it("keeps a comment saved with Esc", async () => {
		const ui = harness([
			(send) => send(SPACE),
			(send) => send(DOWN, ...type("escaped out"), ESC, ESC),
			(send) => send("s"),
		]);

		const result = await annotateFindings(ui, twoFindings);

		assert.deepEqual(result, { cancelled: false, reactions: ["escaped out", null] });
	});

	it("redisplays a saved comment when the finding is revisited", async () => {
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

		const result = await annotateFindings(ui, twoFindings);

		assert.match(idleView, /first pass/);
		assert.match(reopenedEditor, /first pass/);
		assert.deepEqual(result.reactions, ["first pass", "other"]);
	});

	it("marks commented findings in the list", async () => {
		let listView = "";
		const ui = harness([
			(send) => send(SPACE),
			(send) => send(DOWN, ...type("noted"), ENTER, ESC),
			(send, render) => {
				listView = render();
				send("s");
			},
		]);

		await annotateFindings(ui, twoFindings);

		assert.match(listView, /1 commented/);
		assert.match(listView, /first {2}\(no file\):\? {2}📝/);
	});

	it("does not open the comment box on Enter from the card", async () => {
		const ui = harness([
			(send) => send(SPACE),
			// Enter must be inert here; the characters that follow would otherwise become a comment.
			(send) => send(ENTER, ...type("not a comment"), ESC),
			(send) => send("s"),
		]);

		const result = await annotateFindings(ui, twoFindings);

		assert.deepEqual(result.reactions, [null, null]);
	});

	it("clears a comment when the box is emptied", async () => {
		const ui = harness([
			(send) => send(SPACE),
			(send) => send(DOWN, ...type("temporary"), ENTER, DOWN, ...Array(9).fill(BACKSPACE), ENTER, ESC),
			(send) => send("s"),
		]);

		const result = await annotateFindings(ui, twoFindings);

		assert.deepEqual(result.reactions, [null, null]);
	});

	it("saves the whole of a large paste on both the Enter and the Esc path", async () => {
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

		const result = await annotateFindings(ui, twoFindings);

		assert.deepEqual(result.reactions, [paste.text, paste.text]);
	});

	it("keeps a pasted comment intact when the finding is revisited", async () => {
		const paste = bracketedPaste(12);
		const ui = harness([
			(send) => send(SPACE),
			(send) => send(DOWN, paste.keys, ESC, DOWN, ESC, ESC),
			(send) => send("s"),
		]);

		const result = await annotateFindings(ui, twoFindings);

		// Re-entering the box reseeds it from the store, which clears the Editor's paste map — the
		// stored text must already be the real content or it becomes an orphaned marker forever.
		assert.deepEqual(result.reactions, [paste.text, null]);
	});

	it("places the comment box under the label even when a finding quotes it", async () => {
		const quoting = finding({
			title: "Stale doc comment",
			detail: "Your comment on line 5 no longer matches the code.",
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

		await annotateFindings(ui, [quoting, finding({ title: "second" })]);

		const lines = editing.split("\n");
		const lastLabel = lines.map((line) => line.includes("Your comment")).lastIndexOf(true);
		const box = lines.findIndex((line) => line.includes("ZZMARKER"));
		assert.ok(lastLabel >= 0 && box >= 0, "expected both the label and the comment box to render");
		assert.ok(box > lastLabel, `comment box rendered at ${box}, above the label at ${lastLabel}`);
	});

	it("discards every comment when the list is cancelled", async () => {
		const ui = harness([
			(send) => send(SPACE),
			(send) => send(DOWN, ...type("typed then abandoned"), ENTER, ESC),
			(send) => send(ESC),
		]);

		const result = await annotateFindings(ui, twoFindings);

		assert.deepEqual(result, { cancelled: true, reactions: [] });
	});

	it("returns immediately without opening a view when there are no findings", async () => {
		const result = await annotateFindings(harness([]), []);

		assert.deepEqual(result, { cancelled: false, reactions: [] });
	});
});
