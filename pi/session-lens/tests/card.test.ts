import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Theme } from "@earendil-works/pi-coding-agent";
import { visibleWidth } from "@earendil-works/pi-tui";
import { lensCardComponent, renderLensCard, viewportFromTerminal } from "#session-lens/card.ts";
import { calculateLensBudget } from "#session-lens/prompt.ts";

const theme = {
	fg: (_color: string, text: string) => text,
	bold: (text: string) => text,
} as unknown as Theme;

describe("session lens card", () => {
	it("renders a bounded result with explicit overflow and dismissal guidance", () => {
		const budget = calculateLensBudget("explain", { columns: 60, rows: 16 });
		const body = Array.from({ length: 20 }, (_, index) => `Paragraph ${index + 1}`).join("\n\n");
		const lines = renderLensCard(
			{ operation: "explain", body, budget, model: "openai/explain-1", truncated: true },
			60,
			theme,
		);

		assert.ok(lines.length <= budget.maxCardLines);
		assert.match(lines.join("\n"), /Explanation/);
		assert.match(lines.join("\n"), /openai\/explain-1/);
		assert.match(lines.join("\n"), /output exceeded this one-screen card/);
		assert.match(lines.join("\n"), /explainer output limit reached/);
		assert.match(lines.join("\n"), /\/dismiss · next message closes/);
	});

	it("labels loading cards and uses conservative terminal defaults", () => {
		const viewport = viewportFromTerminal({});
		assert.deepEqual(viewport, { columns: 80, rows: 24 });
		const budget = calculateLensBudget("tldr", viewport);
		const lines = renderLensCard({ operation: "tldr", body: "Preparing…", budget, loading: true }, 80, theme);
		assert.match(lines[0] ?? "", /Generating TL;DR/);
	});

	it("keeps every border inside a narrow terminal", () => {
		const budget = calculateLensBudget("rephrase", { columns: 10, rows: 16 });
		const lines = renderLensCard({ operation: "rephrase", body: "Short result", budget }, 10, theme);
		assert.ok(lines.every((line) => visibleWidth(line) <= 10));
	});

	it("recomputes its visible line budget when the terminal is resized", () => {
		const terminal = { columns: 100, rows: 40 };
		const initialBudget = calculateLensBudget("explain", terminal);
		const body = Array.from({ length: 30 }, (_, index) => `Paragraph ${index + 1}`).join("\n\n");
		const component = lensCardComponent({ operation: "explain", body, budget: initialBudget }, theme, terminal);
		const tall = component.render(100);
		terminal.rows = 16;
		const short = component.render(100);
		assert.ok(short.length < tall.length);
		assert.ok(short.length <= calculateLensBudget("explain", terminal).maxCardLines);
	});
});
