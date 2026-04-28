/**
 * Recall tool — semantic memory over past sessions.
 *
 * Spawns the Python recall CLI and returns structured JSON results.
 */

import * as childProcess from "node:child_process";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { getMarkdownTheme } from "@mariozechner/pi-coding-agent";
import { type Component, Container, Markdown, Spacer, Text } from "@mariozechner/pi-tui";
import { type Static, Type } from "@sinclair/typebox";

const RecallToolParams = Type.Object({
	mode: Type.Union([
		Type.Literal("search", { description: "Semantic search by topic" }),
		Type.Literal("list", { description: "Parametric listing by date/filters" }),
		Type.Literal("session", { description: "Full session detail by ID" }),
	]),
	query: Type.Optional(Type.String({ description: "Search query (required for search mode)" })),
	types: Type.Optional(
		Type.Array(Type.String(), { description: "Artifact types: knowledge, decisions, constraints, actions" }),
	),
	crossProject: Type.Optional(Type.Boolean({ description: "Search across all projects" })),
	topK: Type.Optional(Type.Number({ description: "Max results", default: 10 })),
	threshold: Type.Optional(Type.Number({ description: "Min relevance score (0-1)", default: 0.3 })),
	after: Type.Optional(Type.String({ description: "Only results after this date (YYYY-MM-DD)" })),
	before: Type.Optional(Type.String({ description: "Only results before this date (YYYY-MM-DD)" })),
	sessionId: Type.Optional(Type.String({ description: "Session ID for filtering or retrieval" })),
});

type RecallToolInput = Static<typeof RecallToolParams>;

interface CliResult {
	stdout: string;
	stderr: string;
	exitCode: number;
}

interface SearchResult {
	session_id: string;
	text: string;
	title?: string;
	type?: string;
	score?: number;
	created_at?: string;
	started_at?: string;
	ended_at?: string;
}

interface SearchResults {
	results: SearchResult[];
	count: number;
}

interface SessionResult {
	session_id: string;
	started_at: string;
	ended_at?: string;
	sections: Record<string, string>;
}

type ThemeFg = import("@mariozechner/pi-coding-agent").Theme["fg"];
type Theme = import("@mariozechner/pi-coding-agent").Theme;

function spawnRecallCli(args: string[], env: Record<string, string>): CliResult {
	const result = childProcess.spawnSync("recall", args, {
		encoding: "utf-8",
		env: { ...process.env, ...env },
		timeout: 30_000,
	});

	return {
		stdout: result.stdout ?? "",
		stderr: result.stderr || result.error?.message || "",
		exitCode: result.status ?? 1,
	};
}

function buildCliArgs(params: RecallToolInput): string[] {
	switch (params.mode) {
		case "search": {
			if (!params.query) throw new Error("query is required for recall search");
			const args = ["search", params.query];
			if (params.types?.length) args.push("--type", params.types.join(","));
			if (params.crossProject) args.push("--cross-project");
			if (params.topK !== undefined) args.push("--top-k", String(params.topK));
			if (params.threshold !== undefined) args.push("--threshold", String(params.threshold));
			if (params.after) args.push("--after", params.after);
			if (params.before) args.push("--before", params.before);
			return args;
		}
		case "list": {
			const args = ["list"];
			if (params.types?.length) args.push("--type", params.types.join(","));
			if (params.crossProject) args.push("--cross-project");
			if (params.topK !== undefined) args.push("--top-k", String(params.topK));
			if (params.after) args.push("--after", params.after);
			if (params.before) args.push("--before", params.before);
			if (params.sessionId) args.push("--session", params.sessionId);
			return args;
		}
		case "session": {
			if (!params.sessionId) throw new Error("sessionId is required for recall session");
			return ["session", params.sessionId];
		}
	}
}

export function registerRecallTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "recall",
		label: "Recall",
		description:
			"Semantic memory over past sessions. Search for decisions, knowledge, actions, or constraints from previous work.",
		promptSnippet: "Search past sessions for context",
		parameters: RecallToolParams,

		async execute(_id, params, _signal, _onUpdate, ctx) {
			const repo = process.env.BASECAMP_REPO ?? process.env.BASECAMP_PROJECT;
			const claudeSessionId = ctx.sessionManager?.getSessionId();

			const env: Record<string, string> = {};
			if (repo) env.BASECAMP_REPO = repo;
			if (claudeSessionId) env.CLAUDE_SESSION_ID = claudeSessionId;

			let args: string[];
			try {
				args = buildCliArgs(params);
			} catch (error) {
				const message = error instanceof Error ? error.message : String(error);
				return { content: [{ type: "text", text: message }], isError: true, details: null };
			}

			const result = spawnRecallCli(args, env);

			if (result.exitCode !== 0) {
				try {
					const parsed = JSON.parse(result.stdout);
					if (parsed.error) {
						return { content: [{ type: "text", text: parsed.error }], isError: true, details: null };
					}
				} catch {
					// CLI errors are JSON on stdout when possible; otherwise use raw process output.
				}

				const errorMsg = result.stderr || result.stdout || "Unknown error";
				return {
					content: [{ type: "text", text: `Recall CLI failed: ${errorMsg}` }],
					isError: true,
					details: null,
				};
			}

			let parsed: unknown;
			try {
				parsed = JSON.parse(result.stdout);
			} catch {
				return {
					content: [{ type: "text", text: `Failed to parse recall output: ${result.stdout.slice(0, 500)}` }],
					isError: true,
					details: null,
				};
			}

			return {
				content: [{ type: "text", text: formatTextContent(params.mode, parsed) }],
				details: { mode: params.mode, data: parsed },
			};
		},

		renderCall(args, theme, _context) {
			const mode = args.mode || "search";
			let preview = "";

			switch (mode) {
				case "search":
					preview = args.query || "...";
					break;
				case "list":
					preview = args.after ? `after ${args.after}` : "recent sessions";
					break;
				case "session":
					preview = args.sessionId || "...";
					break;
			}

			if (preview.length > 60) preview = `${preview.slice(0, 60)}...`;

			const text = `${theme.fg("toolTitle", theme.bold("recall "))}${theme.fg("accent", mode)} ${theme.fg("dim", preview)}`;
			return new Text(text, 0, 0);
		},

		renderResult(result, { expanded }, theme, _context) {
			const details = result.details as { mode: string; data: unknown } | null;
			const fg = theme.fg.bind(theme);
			const mdTheme = getMarkdownTheme();

			if (!details) {
				const text = result.content[0];
				return new Text(text?.type === "text" ? text.text : "(no output)", 0, 0);
			}

			if (details.mode === "session") {
				return renderSessionResult(details.data as SessionResult, expanded, fg, mdTheme, theme);
			}

			return renderSearchResults(details.data as SearchResults, details.mode, expanded, fg, mdTheme, theme);
		},
	});
}

function formatTextContent(mode: string, data: unknown): string {
	switch (mode) {
		case "search":
		case "list": {
			const results = data as SearchResults;
			if (results.count === 0) return "No results found.";

			const lines = [`Found ${results.count} result(s):\n`];
			for (const r of results.results.slice(0, 10)) {
				const score = r.score ? ` (score: ${r.score.toFixed(2)})` : "";
				const title = r.title ? ` — ${r.title}` : "";
				const type = r.type ? ` [${r.type}]` : "";
				lines.push(`• ${r.session_id}${type}${title}${score}`);
				const preview = r.text.slice(0, 200);
				if (preview) lines.push(`  ${preview}${r.text.length > 200 ? "..." : ""}`);
				lines.push("");
			}
			if (results.count > 10) lines.push(`... and ${results.count - 10} more`);
			return lines.join("\n");
		}
		case "session": {
			const session = data as SessionResult;
			const lines = [`Session: ${session.session_id}`, `Started: ${session.started_at}`];
			if (session.ended_at) lines.push(`Ended: ${session.ended_at}`);
			lines.push("");
			for (const [section, text] of Object.entries(session.sections)) {
				lines.push(`## ${section}`);
				lines.push(text);
				lines.push("");
			}
			return lines.join("\n");
		}
		default:
			return JSON.stringify(data, null, 2);
	}
}

function renderSearchResults(
	results: SearchResults,
	mode: string,
	expanded: boolean,
	fg: ThemeFg,
	mdTheme: ReturnType<typeof getMarkdownTheme>,
	theme: Theme,
): Component {
	const container = new Container();
	const icon = results.count > 0 ? fg("success", "✓") : fg("muted", "○");
	const label = mode === "search" ? "semantic search" : "list";
	container.addChild(
		new Text(
			`${icon} ${fg("toolTitle", theme.bold("recall "))}${fg("accent", label)} ${fg("dim", `— ${results.count} result(s)`)}`,
			0,
			0,
		),
	);

	if (results.count === 0) {
		container.addChild(new Spacer(1));
		container.addChild(new Text(fg("muted", "No results found."), 0, 0));
		return container;
	}

	if (!expanded) {
		container.addChild(new Spacer(1));
		for (const r of results.results.slice(0, 3)) {
			container.addChild(renderResultLine(r, fg));
		}
		if (results.count > 3) {
			container.addChild(new Text(fg("muted", `... and ${results.count - 3} more`), 0, 0));
		}
		container.addChild(new Text(fg("muted", "(Ctrl+O to expand)"), 0, 0));
		return container;
	}

	container.addChild(new Spacer(1));
	container.addChild(new Text(fg("muted", "Results"), 0, 0));

	for (const r of results.results) {
		container.addChild(renderResultLine(r, fg));

		if (r.text) {
			const preview = r.text.slice(0, 300);
			container.addChild(new Markdown(preview + (r.text.length > 300 ? "..." : ""), 0, 0, mdTheme));
		}
		container.addChild(new Spacer(1));
	}

	return container;
}

function renderResultLine(result: SearchResult, fg: ThemeFg): Component {
	const score = result.score ? fg("muted", ` (${result.score.toFixed(2)})`) : "";
	const title = result.title ? fg("dim", ` — ${result.title}`) : "";
	const type = result.type ? fg("accent", ` [${result.type}]`) : "";
	return new Text(fg("accent", `• ${result.session_id}`) + type + title + score, 0, 0);
}

function renderSessionResult(
	session: SessionResult,
	expanded: boolean,
	fg: ThemeFg,
	mdTheme: ReturnType<typeof getMarkdownTheme>,
	theme: Theme,
): Component {
	const container = new Container();
	container.addChild(
		new Text(
			`${fg("success", "✓")} ${fg("toolTitle", theme.bold("recall session"))} ${fg("accent", session.session_id)}`,
			0,
			0,
		),
	);
	container.addChild(
		new Text(
			fg("dim", `Started: ${session.started_at}${session.ended_at ? ` — Ended: ${session.ended_at}` : ""}`),
			0,
			0,
		),
	);

	if (!expanded) {
		container.addChild(new Spacer(1));
		const sectionNames = Object.keys(session.sections);
		if (sectionNames.length > 0) {
			container.addChild(new Text(fg("muted", `Sections: ${sectionNames.join(", ")}`), 0, 0));
		}
		container.addChild(new Text(fg("muted", "(Ctrl+O to expand)"), 0, 0));
		return container;
	}

	for (const [section, text] of Object.entries(session.sections)) {
		container.addChild(new Spacer(1));
		container.addChild(new Text(fg("muted", section), 0, 0));
		if (text) {
			container.addChild(new Markdown(text, 0, 0, mdTheme));
		} else {
			container.addChild(new Text(fg("muted", "(empty)"), 0, 0));
		}
	}

	return container;
}
