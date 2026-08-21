import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Theme } from "@earendil-works/pi-coding-agent";
import { renderLensCard, viewportFromTerminal } from "#session-lens/card.ts";
import { calculateLensBudget } from "#session-lens/prompt.ts";

const theme = {
	fg: (_color: string, text: string) => text,
	bold: (text: string) => text,
} as unknown as Theme;

describe("session lens card", () => {
	it("renders a bounded result with explicit overflow and dismissal guidance", () => {
		const budget = calculateLensBudget("explain", { columns: 60, rows: 16 });
		const body = Array.from({ length: 20 }, (_, index) => `Paragraph ${index + 1}`).join("\n\n");
		const lines = renderLensCard({ operation: "explain", body, budget, model: "openai/explain-1" }, 60, theme);

		assert.ok(lines.length <= budget.maxCardLines);
		assert.match(lines.join("\n"), /Explanation/);
		assert.match(lines.join("\n"), /openai\/explain-1/);
		assert.match(lines.join("\n"), /output exceeded this one-screen card/);
		assert.match(lines.join("\n"), /\/dismiss · next message closes/);
	});

	it("labels loading cards and uses conservative terminal defaults", () => {
		const viewport = viewportFromTerminal({});
		assert.deepEqual(viewport, { columns: 80, rows: 24 });
		const budget = calculateLensBudget("tldr", viewport);
		const lines = renderLensCard({ operation: "tldr", body: "Preparing…", budget, loading: true }, 80, theme);
		assert.match(lines[0] ?? "", /Generating TL;DR/);
	});
});
