/**
 * Skill resolution for agents.
 *
 * Resolves skill names declared in agent frontmatter to file paths
 * using pi's loadSkills() API, reads their content, and injects
 * them into the agent's system prompt as XML blocks.
 *
 * Subagents pass --no-skills to suppress pi's own skill discovery
 * since skills are already baked into the prompt.
 */

import { getAgentDir, loadSkills, type Skill } from "@earendil-works/pi-coding-agent";
import type { PiSwarmDependencies } from "../dependencies.ts";

// ============================================================================
// Types
// ============================================================================

export interface ResolvedSkill {
	name: string;
	path: string;
	content: string;
}

export interface SkillResolution {
	resolved: ResolvedSkill[];
	missing: string[];
}

// ============================================================================
// Resolution
// ============================================================================

/**
 * Resolve skill names to file paths using pi's skill discovery.
 * Returns resolved skills (with content) and any names that weren't found.
 */
export function resolveSkills(
	skillNames: string[],
	cwd: string,
	deps: Pick<PiSwarmDependencies, "readSkillContent">,
): SkillResolution {
	if (skillNames.length === 0) return { resolved: [], missing: [] };

	const { skills } = loadSkills({ cwd, agentDir: getAgentDir(), skillPaths: [], includeDefaults: true });
	const skillMap = new Map<string, Skill>();
	for (const skill of skills) {
		skillMap.set(skill.name, skill);
	}

	const resolved: ResolvedSkill[] = [];
	const missing: string[] = [];

	for (const name of skillNames) {
		const trimmed = name.trim();
		if (!trimmed) continue;

		const skill = skillMap.get(trimmed);
		if (!skill) {
			missing.push(trimmed);
			continue;
		}

		const content = deps.readSkillContent(skill.filePath);
		if (content !== null) {
			resolved.push({ name: trimmed, path: skill.filePath, content });
		} else {
			missing.push(trimmed);
		}
	}

	return { resolved, missing };
}

// ============================================================================
// Prompt Injection
// ============================================================================

/**
 * Build XML skill injection block for appending to a system prompt.
 */
export function buildSkillInjection(
	skills: ResolvedSkill[],
	deps: Pick<PiSwarmDependencies, "buildSkillBlock">,
): string {
	if (skills.length === 0) return "";

	return skills.map((s) => deps.buildSkillBlock(s.name, s.content)).join("\n\n");
}
