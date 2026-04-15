/**
 * Agent discovery — three-tier scan with frontmatter parsing.
 *
 * Priority (highest wins on name collision):
 *   1. Project: .basecamp/agents/ (walks up from cwd)
 *   2. User:    ~/.basecamp/agents/
 *   3. Builtin: extension/agents/ (shipped with basecamp)
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { AgentConfig, ModelStrategy } from "./types.ts";

const USER_AGENTS_DIR = path.join(os.homedir(), ".basecamp", "agents");
const BUILTIN_AGENTS_DIR = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "builtin",
);

// ============================================================================
// Frontmatter Parser
// ============================================================================

interface ParsedFile {
  frontmatter: Record<string, string>;
  body: string;
}

function parseFrontmatter(content: string): ParsedFile {
  const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/);
  if (!match) return { frontmatter: {}, body: content.trim() };

  const fm: Record<string, string> = {};
  for (const line of match[1].split("\n")) {
    const colon = line.indexOf(":");
    if (colon === -1) continue;
    const key = line.slice(0, colon).trim();
    const value = line.slice(colon + 1).trim();
    if (key) fm[key] = value;
  }
  return { frontmatter: fm, body: match[2].trim() };
}

function parseCsv(value: string | undefined): string[] | undefined {
  if (!value) return undefined;
  const items = value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return items.length > 0 ? items : undefined;
}

// ============================================================================
// Directory Scanner
// ============================================================================

function loadAgentsFromDir(
  dir: string,
  source: AgentConfig["source"],
): AgentConfig[] {
  if (!fs.existsSync(dir)) return [];

  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch {
    return [];
  }

  const agents: AgentConfig[] = [];
  for (const entry of entries) {
    if (!entry.name.endsWith(".md")) continue;
    if (!entry.isFile() && !entry.isSymbolicLink()) continue;

    const filePath = path.join(dir, entry.name);
    let content: string;
    try {
      content = fs.readFileSync(filePath, "utf-8");
    } catch {
      continue;
    }

    const { frontmatter: fm, body } = parseFrontmatter(content);
    if (!fm.name || !fm.description) continue;

    // Model strategy: "inherit", "default", or an explicit model string.
    // Missing model defaults to "default" (pi's default model).
    const model: ModelStrategy = (fm.model as ModelStrategy) || "default";

    agents.push({
      name: fm.name,
      description: fm.description,
      model,
      thinking: fm.thinking || undefined,
      tools: parseCsv(fm.tools),
      skills: parseCsv(fm.skills),
      systemPrompt: body,
      source,
      filePath,
    });
  }

  return agents;
}

// ============================================================================
// Project Directory Walk
// ============================================================================

function findProjectAgentsDir(cwd: string): string | null {
  let dir = cwd;
  while (true) {
    const candidate = path.join(dir, ".basecamp", "agents");
    try {
      if (fs.statSync(candidate).isDirectory()) return candidate;
    } catch {
      // Not found at this level, keep walking up.
    }
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

// ============================================================================
// Public API
// ============================================================================

/**
 * Discover all agent definitions, merging by priority.
 * Project agents override user agents which override builtins.
 */
export function discoverAgents(cwd: string): AgentConfig[] {
  const builtin = loadAgentsFromDir(BUILTIN_AGENTS_DIR, "builtin");
  const user = loadAgentsFromDir(USER_AGENTS_DIR, "user");
  const projectDir = findProjectAgentsDir(cwd);
  const project = projectDir
    ? loadAgentsFromDir(projectDir, "project")
    : [];

  // Name-keyed merge: last write wins (project > user > builtin)
  const map = new Map<string, AgentConfig>();
  for (const a of builtin) map.set(a.name, a);
  for (const a of user) map.set(a.name, a);
  for (const a of project) map.set(a.name, a);
  return Array.from(map.values());
}
