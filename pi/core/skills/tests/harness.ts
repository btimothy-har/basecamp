/**
 * Shared harness for skill-tool tests: command fixtures, tool capture, and
 * the render helpers used to assert TUI output.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerSkillTool } from "#core/skills/skill.ts";

export interface SkillCommand {
	name: string;
	description?: string;
	source: "skill";
	sourceInfo: { path: string };
}

export interface ToolResult {
	content: { type: string; text: string }[];
	isError?: boolean;
	details?: unknown;
}

export interface RegisteredTool {
	name: string;
	execute(toolCallId: string, params: { name: string; reference?: string }): Promise<ToolResult>;
	renderCall?: (args: { name?: string; reference?: string }, theme: ThemeStub) => unknown;
	renderResult?: (result: ToolResult, meta: { isPartial: boolean }, theme: ThemeStub) => unknown;
}

export interface ThemeStub {
	fg: (_token: string, text: string) => string;
	bold: (text: string) => string;
}

export const themeStub: ThemeStub = {
	fg: (_token, text) => text,
	bold: (text) => text,
};

export function skillCommands(paths: Record<string, string>): SkillCommand[] {
	return Object.entries(paths).map(([name, path]) => ({
		name: `skill:${name}`,
		description: `${name} skill for testing.`,
		source: "skill" as const,
		sourceInfo: { path },
	}));
}

export function captureSkillTool(commands: SkillCommand[]): RegisteredTool {
	let captured: RegisteredTool | undefined;
	const pi = {
		registerTool(tool: RegisteredTool) {
			captured = tool;
		},
		getCommands: () => commands,
	} as unknown as ExtensionAPI;
	registerSkillTool(pi);
	if (!captured) throw new Error("skill tool not registered");
	return captured;
}

/** Render a renderResult Text to plain lines for assertion. */
export function renderToolResult(tool: RegisteredTool, result: ToolResult): string {
	const text = (tool.renderResult as NonNullable<RegisteredTool["renderResult"]>)(
		result,
		{ isPartial: false },
		themeStub,
	) as { render: (width: number) => string[] };
	return text.render(120).join("\n");
}

/** Render a renderCall Text to plain lines for assertion. */
export function renderToolCall(tool: RegisteredTool, args: { name?: string; reference?: string }): string {
	const text = (tool.renderCall as NonNullable<RegisteredTool["renderCall"]>)(args, themeStub) as {
		render: (width: number) => string[];
	};
	return text.render(120).join("\n");
}
