import { getMarkdownTheme, type Theme } from "@earendil-works/pi-coding-agent";
import { type Component, Markdown, truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";
import { calculateLensBudget } from "./prompt.ts";
import type { LensBudget, LensOperation, LensViewport } from "./types.ts";

const TITLES: Record<LensOperation, string> = {
	explain: "Explanation",
	tldr: "TL;DR",
	rephrase: "Rephrased session",
};

export interface LensCardInput {
	operation: LensOperation;
	body: string;
	budget: LensBudget;
	model?: string;
	loading?: boolean;
	truncated?: boolean;
}

function borderedRow(content: string, width: number, theme: Theme): string {
	const innerWidth = Math.max(1, width - 2);
	return `${theme.fg("border", "│")}${truncateToWidth(content, innerWidth, "…", true)}${theme.fg("border", "│")}`;
}

function titleRow(title: string, width: number, theme: Theme): string {
	const innerWidth = Math.max(1, width - 2);
	const label = truncateToWidth(` ${title} `, innerWidth, "…");
	const remaining = Math.max(0, innerWidth - visibleWidth(label));
	return theme.fg("border", `╭${label}${"─".repeat(remaining)}╮`);
}

export function renderLensCard(input: LensCardInput, width: number, theme: Theme): string[] {
	const safeWidth = Math.max(4, width);
	const title = input.loading ? `Generating ${TITLES[input.operation]}…` : TITLES[input.operation];
	const markdown = new Markdown(input.body, 0, 0, getMarkdownTheme());
	const rendered = markdown.render(Math.max(1, safeWidth - 4));
	const overflow = rendered.length > input.budget.maxContentLines;
	const content = overflow
		? [
				...rendered.slice(0, Math.max(0, input.budget.maxContentLines - 1)),
				theme.fg("warning", "… output exceeded this one-screen card"),
			]
		: rendered;

	const lines = [titleRow(theme.bold(title), safeWidth, theme)];
	if (input.model) lines.push(borderedRow(` ${theme.fg("dim", input.model)}`, safeWidth, theme));
	for (const line of content) lines.push(borderedRow(` ${line}`, safeWidth, theme));
	if (input.truncated)
		lines.push(borderedRow(` ${theme.fg("warning", "explainer output limit reached")}`, safeWidth, theme));
	lines.push(borderedRow(` ${theme.fg("dim", "/dismiss · next message closes")}`, safeWidth, theme));
	lines.push(theme.fg("border", `╰${"─".repeat(Math.max(1, safeWidth - 2))}╯`));
	return lines.slice(0, input.budget.maxCardLines);
}

export function lensCardComponent(
	input: LensCardInput,
	theme: Theme,
	terminal?: { columns?: number; rows?: number },
): Component {
	return {
		invalidate(): void {},
		render(width: number): string[] {
			const budget = terminal ? calculateLensBudget(input.operation, viewportFromTerminal(terminal)) : input.budget;
			return renderLensCard({ ...input, budget }, width, theme);
		},
	};
}

export function viewportFromTerminal(terminal: { columns?: number; rows?: number }): LensViewport {
	return {
		columns: terminal.columns ?? 80,
		rows: terminal.rows ?? 24,
	};
}
