import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { renderTaskWidgetLines, type TaskProgressRenderTheme, type TaskProgressSnapshot } from "../widget.ts";

const theme: TaskProgressRenderTheme = { fg: (_color, text) => text };

function render(snapshot: TaskProgressSnapshot, width = 60): string[] {
	return renderTaskWidgetLines(snapshot, theme, width);
}

describe("tasks/widget active description", () => {
	it("renders the active task's description beneath it, but not other tasks'", () => {
		const out = render({
			goal: "Ship it",
			tasks: [
				{ label: "Build", status: "active", description: "Wire the widget" },
				{ label: "Test", status: "pending", description: "Add tests" },
			],
		}).join("\n");

		assert.match(out, /→ Build/);
		assert.match(out, /Wire the widget/);
		assert.match(out, /☐ Test/);
		assert.doesNotMatch(out, /Add tests/);
	});

	it("caps a long description to the row limit and appends an ellipsis", () => {
		const long = "word ".repeat(80).trim();
		const lines = render({ goal: null, tasks: [{ label: "Big", status: "active", description: long }] }, 40);

		const descLines = lines.filter((line) => line.includes("word"));
		assert.equal(descLines.length, 2);
		assert.ok(lines.some((line) => line.includes("…")));
	});

	it("shows no description line when the active task has none", () => {
		const lines = render({ goal: null, tasks: [{ label: "Solo", status: "active" }] });
		const contentLines = lines.filter((line) => line.includes("│"));
		assert.equal(contentLines.length, 1);
		assert.match(contentLines[0]!, /→ Solo/);
	});

	it("shows no description when there is no active task", () => {
		const out = render({
			goal: null,
			tasks: [{ label: "Later", status: "pending", description: "not shown yet" }],
		}).join("\n");
		assert.doesNotMatch(out, /not shown yet/);
	});
});
