/**
 * Skill resolution for worker agents.
 *
 * Resolves skill names declared in agent frontmatter to file paths
 * using pi's loadSkills() API, reads their content, and injects
 * them into the agent's system prompt as XML blocks.
 *
 * Workers pass --no-skills to suppress pi's own skill discovery
 * since skills are already baked into the prompt.
 */

import * as fs from "node:fs";
import { loadSkills, stripFrontmatter, type Skill } from "@mariozechner/pi-coding-agent";

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
): SkillResolution {
  if (skillNames.length === 0) return { resolved: [], missing: [] };

  const { skills } = loadSkills({ cwd });
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

    try {
      const raw = fs.readFileSync(skill.filePath, "utf-8");
      const content = stripFrontmatter(raw).trim();
      if (content) {
        resolved.push({ name: trimmed, path: skill.filePath, content });
      } else {
        missing.push(trimmed);
      }
    } catch {
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
export function buildSkillInjection(skills: ResolvedSkill[]): string {
  if (skills.length === 0) return "";

  return skills
    .map((s) => `<skill name="${escapeXml(s.name)}">\n${s.content}\n</skill>`)
    .join("\n\n");
}

function escapeXml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
