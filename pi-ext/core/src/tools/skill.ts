/**
 * Skill tool — load skill instructions on demand, once per session.
 *
 * Reads the named skill file and returns its content wrapped in an XML
 * block. Subsequent calls for the same skill in the same session return
 * a short dedup notice rather than re-loading the file.
 *
 * Use `discover` to browse or search available skills and get metadata.
 * Use this tool to actually load the instructions.
 */

import type { ExtensionAPI, Theme } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { loadSkillBlock } from "./skill-content";
import { hasInvokedSkill, trackSkillInvocation } from "./skill-tracker.ts";

const SkillParams = Type.Object(
	{
		name: Type.String({
			description: 'Exact name of the skill to load (e.g. "python-development").',
		}),
	},
	{
		description: "Load the instructions for a named skill. Each skill is loaded at most once per session.",
	},
);

function renderPartial(theme: Theme) {
	const { Text } = require("@mariozechner/pi-tui");
	return new Text(theme.fg("dim", "..."), 0, 0);
}

function renderCall(args: { name?: string }, theme: Theme) {
	const { Text } = require("@mariozechner/pi-tui");
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

	const { Text } = require("@mariozechner/pi-tui");
	const text = result.content?.find((item) => item.type === "text")?.text ?? "";

	const loaded = text.match(/^<skill name="([^"]+)">/);
	if (loaded) {
		return new Text(theme.fg("success", "✓") + theme.fg("dim", ` ${loaded[1]} loaded`), 0, 0);
	}

	const alreadyLoaded = text.match(/^Skill "([^"]+)" already loaded this session\.$/);
	if (alreadyLoaded) {
		return new Text(theme.fg("dim", `${alreadyLoaded[1]} already loaded`), 0, 0);
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
			"Each skill is loaded at most once per session — repeat calls return a short notice. " +
			'Use discover({ type: "skills" }) to browse available skills.',

		parameters: SkillParams,

		async execute(_id, params, _signal, _onUpdate, _ctx) {
			const { name } = params;

			// Dedup: already loaded this session.
			if (hasInvokedSkill(name)) {
				return {
					details: null,
					content: [{ type: "text", text: `Skill "${name}" already loaded this session.` }],
				};
			}

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
