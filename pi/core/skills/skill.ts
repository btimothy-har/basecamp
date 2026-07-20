/**
 * Skill tool — load skill instructions on demand.
 *
 * Reads the named skill file and returns its content wrapped in an XML
 * block. A skill may be loaded multiple times per session; each call
 * re-reads the file and records the invocation for tracking.
 *
 * Available skills and descriptions are listed in the capabilities index.
 * Use this tool to load the full instructions.
 */

import type { ExtensionAPI, Theme } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { isModelInvocationDisabled, loadSkillBlock } from "./skill-content.ts";
import { trackSkillInvocation } from "./tracker.ts";

const SkillParams = Type.Object(
	{
		name: Type.String({
			description: 'Exact name of the skill to load (e.g. "python-development").',
		}),
	},
	{
		description: "Load the instructions for a named skill.",
	},
);

function renderPartial(theme: Theme) {
	const { Text } = require("@earendil-works/pi-tui");
	return new Text(theme.fg("dim", "..."), 0, 0);
}

function renderCall(args: { name?: string }, theme: Theme) {
	const { Text } = require("@earendil-works/pi-tui");
	const name = args.name || "...";
	const preview = name.length > 50 ? `${name.slice(0, 50)}...` : name;
	return new Text(theme.fg("toolTitle", theme.bold("skill ")) + theme.fg("dim", preview), 0, 0);
}

function renderResult(
	result: { content?: Array<{ type: string; text?: string }> },
	meta: { isPartial: boolean },
	theme: Theme,
) {
	if (meta.isPartial) return renderPartial(theme);

	const { Text } = require("@earendil-works/pi-tui");
	const text = result.content?.find((item) => item.type === "text")?.text ?? "";

	const loaded = text.match(/^<skill name="([^"]+)">/);
	if (loaded) {
		return new Text(theme.fg("success", "✓") + theme.fg("dim", ` ${loaded[1]} loaded`), 0, 0);
	}

	const notFound = text.match(/^No skill found with name "([^"]+)"\./);
	if (notFound) {
		return new Text(theme.fg("error", `${notFound[1]} not found`), 0, 0);
	}

	if (text.startsWith("Failed to read skill file at ")) {
		return new Text(theme.fg("error", "skill load failed"), 0, 0);
	}

	return new Text(theme.fg("dim", "skill processed"), 0, 0);
}

export function registerSkillTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "skill",
		label: "Skill",
		description:
			"Load full instructions for a named skill. " +
			"Available skills are listed in the system prompt capabilities index.",

		parameters: SkillParams,

		async execute(_id, params, _signal, _onUpdate, _ctx) {
			const { name } = params;

			// Resolve skill path from pi commands.
			const command = pi
				.getCommands()
				.filter((c) => c.source === "skill")
				.find((c) => c.name.replace(/^skill:/, "") === name);

			if (!command) {
				const available = pi
					.getCommands()
					.filter((c) => c.source === "skill")
					.map((c) => c.name.replace(/^skill:/, ""));
				const hint = available.length > 0 ? ` Available skills: ${available.join(", ")}.` : "";
				return {
					details: null,
					isError: true,
					content: [{ type: "text", text: `No skill found with name "${name}".${hint}` }],
				};
			}

			if (isModelInvocationDisabled(command.sourceInfo.path)) {
				return {
					details: null,
					isError: true,
					content: [
						{
							type: "text",
							text: `Skill "${name}" is user-invoked only (via /skill:${name}) and cannot be loaded by the agent.`,
						},
					],
				};
			}

			const filePath = command.sourceInfo.path;
			const block = loadSkillBlock(name, filePath);
			if (block === null) {
				return {
					details: null,
					isError: true,
					content: [{ type: "text", text: `Failed to read skill file at ${filePath}.` }],
				};
			}

			trackSkillInvocation(name);

			return {
				details: null,
				content: [{ type: "text", text: block }],
			};
		},
		renderCall,
		renderResult,
	});
}
