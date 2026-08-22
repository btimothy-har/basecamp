/**
 * Skill tool — load skill instructions on demand.
 *
 * Reads the named skill file and returns its content wrapped in an XML
 * block. A skill may be loaded multiple times per session; each call
 * re-reads the file and records the invocation for tracking.
 *
 * With `reference`, returns one skill-relative document instead of the full
 * instructions — gated on the skill already being loaded this session and
 * confined to the skill's own directory.
 *
 * Available skills and descriptions are listed in the capabilities index.
 * Use this tool to load the full instructions.
 */

import * as path from "node:path";
import type { ExtensionAPI, Theme } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { isStrictlyWithin } from "#core/host/paths.ts";
import {
	buildSkillReferenceBlock,
	isModelInvocationDisabled,
	loadSkillBlock,
	readSkillContent,
} from "./skill-content.ts";
import { hasInvokedSkill, trackSkillInvocation } from "./tracker.ts";

const SkillParams = Type.Object(
	{
		name: Type.String({
			description: 'Exact name of the skill to load (e.g. "python-development").',
		}),
		reference: Type.Optional(
			Type.String({
				description:
					'Skill-relative path to one reference document (e.g. "references/api.md"). ' +
					"The skill must already be loaded in this session; returns the document instead of the full instructions.",
			}),
		),
	},
	{
		description: "Load the instructions for a named skill.",
	},
);

function renderPartial(theme: Theme) {
	const { Text } = require("@earendil-works/pi-tui");
	return new Text(theme.fg("dim", "..."), 0, 0);
}

function renderCall(args: { name?: string; reference?: string }, theme: Theme) {
	const { Text } = require("@earendil-works/pi-tui");
	const name = args.name || "...";
	const preview = args.reference ? `${name} · ${args.reference}` : name;
	const shown = preview.length > 50 ? `${preview.slice(0, 50)}...` : preview;
	return new Text(theme.fg("toolTitle", theme.bold("skill ")) + theme.fg("dim", shown), 0, 0);
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

	const loadedReference = text.match(/^<skill-reference skill="([^"]+)">/);
	if (loadedReference) {
		return new Text(theme.fg("success", "✓") + theme.fg("dim", ` ${loadedReference[1]} reference loaded`), 0, 0);
	}

	const notFound = text.match(/^No skill found with name "([^"]+)"\./);
	if (notFound) {
		return new Text(theme.fg("error", `${notFound[1]} not found`), 0, 0);
	}

	if (text.startsWith("Failed to read skill file at ")) {
		return new Text(theme.fg("error", "skill load failed"), 0, 0);
	}

	if (text.startsWith("Failed to read reference file at ") || /^(?:Reference|Skill) "/.test(text)) {
		return new Text(theme.fg("error", "skill reference failed"), 0, 0);
	}

	return new Text(theme.fg("dim", "skill processed"), 0, 0);
}

/**
 * Resolve a skill-relative reference path, confined to the skill's own directory.
 *
 * The reference argument is model-authored and this channel bypasses the
 * path-guarded `read` tool, so it must stay strictly narrower: no absolute
 * paths, no traversal outside the skill directory.
 */
function resolveSkillReference(skillDir: string, reference: string): string | null {
	if (path.isAbsolute(reference)) return null;
	const resolved = path.resolve(skillDir, reference);
	return isStrictlyWithin(resolved, skillDir) ? resolved : null;
}

function errorResult(text: string) {
	return { details: null, isError: true, content: [{ type: "text" as const, text }] };
}

export function registerSkillTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "skill",
		label: "Skill",
		description:
			"Load full instructions for a named skill into this agent's active context. " +
			"Available skills are listed in the system prompt capabilities index. " +
			"Loaded instructions stay available across turns and tasks, so relevance alone is not a reason to reload; " +
			"reload only when the instructions have left context or you need an intentional refresh. " +
			"Pass reference to load one reference document (a skill-relative path such as references/api.md) " +
			"from a skill already loaded in this session, instead of the full instructions.",

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

			if (params.reference !== undefined) {
				if (!hasInvokedSkill(name)) {
					return errorResult(
						`Skill "${name}" is not loaded in this session. ` +
							`Load it first with skill({ name: "${name}" }) before requesting its reference files.`,
					);
				}
				const skillDir = path.dirname(filePath);
				const referencePath = resolveSkillReference(skillDir, params.reference);
				if (!referencePath) {
					return errorResult(
						`Reference "${params.reference}" is not a valid skill-relative path under the "${name}" skill directory.`,
					);
				}
				const content = readSkillContent(referencePath);
				if (content === null) {
					return errorResult(`Failed to read reference file at ${referencePath}.`);
				}
				trackSkillInvocation(name);
				return {
					details: null,
					content: [{ type: "text", text: buildSkillReferenceBlock(name, content) }],
				};
			}

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
