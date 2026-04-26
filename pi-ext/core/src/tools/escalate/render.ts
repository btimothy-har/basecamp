import type { AgentToolResult, Theme, ToolRenderResultOptions } from "@mariozechner/pi-coding-agent";
import type { Component } from "@mariozechner/pi-tui";
import type { Question, QuestionAnswer } from "./types.js";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function renderCall(args: { questions: Question[] }, theme: Theme, _context: any): Component {
	const { Text } = require("@mariozechner/pi-tui");
	const qs = args.questions;
	const preview = qs?.[0]?.question ?? "...";
	const trimmed = preview.length > 60 ? `${preview.slice(0, 60)}...` : preview;
	const suffix = qs && qs.length > 1 ? ` (+${qs.length - 1} more)` : "";
	return new Text(theme.fg("toolTitle", theme.bold("escalate ")) + theme.fg("dim", trimmed + suffix), 0, 0);
}

function truncate(text: string, max: number): string {
	const oneLine = text.replace(/\n/g, " ").trim();
	return oneLine.length > max ? `${oneLine.slice(0, max)}...` : oneLine;
}

function formatAnswer(qa: QuestionAnswer): string {
	if ("selections" in qa) {
		const parts = qa.selections.join(", ");
		const contextIcon = qa.context ? "💬 " : "";
		return parts ? `${contextIcon}${parts}` : truncate(qa.context ?? "", 60);
	}
	return truncate(qa.answer, 60);
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function renderResult(
	result: AgentToolResult<QuestionAnswer[] | null>,
	_options: ToolRenderResultOptions,
	theme: Theme,
	_context: any,
): Component {
	const { Text } = require("@mariozechner/pi-tui");
	const qaList = result.details;
	if (!qaList) {
		return new Text(theme.fg("warning", "⚠") + theme.fg("dim", " dismissed"), 0, 0);
	}
	const lines = qaList.map((qa) => `${qa.question}: ${formatAnswer(qa)}`).join("\n");
	return new Text(theme.fg("accent", lines), 0, 0);
}
