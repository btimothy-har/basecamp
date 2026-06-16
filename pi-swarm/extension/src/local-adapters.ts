import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { stripFrontmatter } from "@earendil-works/pi-coding-agent";
import type { PiSwarmDependencies, TaskProgressSnapshot, TaskProgressTheme, WorkspaceState } from "./dependencies.ts";

const SKILL_TRACKER_KEY = Symbol.for("basecamp.skillTracker");

interface SkillTrackerState {
	invokedSkills: Set<string>;
}

type GlobalWithSkillTracker = typeof globalThis & {
	[SKILL_TRACKER_KEY]?: SkillTrackerState;
};

interface ModelAliasConfig {
	version?: unknown;
	aliases?: unknown;
}

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
	return !!value && typeof value === "object" && !Array.isArray(value);
}

function normalizeAliasMap(value: unknown): Record<string, string> | null {
	if (!isRecord(value)) return null;
	const normalized: Record<string, string> = {};
	for (const [alias, model] of Object.entries(value)) {
		const trimmedAlias = alias.trim();
		if (trimmedAlias.length === 0 || typeof model !== "string" || model.trim().length === 0) return null;
		if (normalized[trimmedAlias] !== undefined) return null;
		normalized[trimmedAlias] = model.trim();
	}
	return normalized;
}

function defaultModelAliasConfigPath(homeDir = homedir()): string {
	return path.join(homeDir, ".pi", "model-aliases", "config.json");
}

function loadModelAliasConfig(configPath = defaultModelAliasConfigPath()): Record<string, string> {
	let raw: string;
	try {
		raw = readFileSync(configPath, "utf8");
	} catch {
		return {};
	}

	let parsed: unknown;
	try {
		parsed = JSON.parse(raw);
	} catch {
		return {};
	}
	if (!isRecord(parsed)) return {};

	const config = parsed as ModelAliasConfig;
	if (config.version !== 1) return {};
	return normalizeAliasMap(config.aliases) ?? {};
}

function getSkillTrackerState(): SkillTrackerState {
	const globalObject = globalThis as GlobalWithSkillTracker;
	globalObject[SKILL_TRACKER_KEY] ??= { invokedSkills: new Set<string>() };
	return globalObject[SKILL_TRACKER_KEY];
}

function getSharedSkillTrackerSet(): Set<string> | null {
	const shared = (globalThis as { [SKILL_TRACKER_KEY]?: { invokedSkills?: unknown } })[SKILL_TRACKER_KEY];
	return shared?.invokedSkills instanceof Set ? (shared.invokedSkills as Set<string>) : null;
}

function hasInvokedSkill(name: string): boolean {
	const normalized = name.trim();
	if (!normalized) return false;
	const local = getSkillTrackerState().invokedSkills;
	if (local.has(normalized)) return true;
	return getSharedSkillTrackerSet()?.has(normalized) ?? false;
}

function trackInvokedSkill(name: string): void {
	const normalized = name.trim();
	if (!normalized) return;
	getSkillTrackerState().invokedSkills.add(normalized);
	const shared = getSharedSkillTrackerSet();
	if (shared) shared.add(normalized);
}

/**
 * Best-effort skill invocation tracking.
 *
 * Tracks local skill invocations and mirrors them into the shared tracker key
 * used by the main Basecamp extension when present.
 */
const skillTrackingInstallations = new WeakSet<ExtensionAPI>();

export function attachPiSwarmSkillTracking(pi: ExtensionAPI): void {
	if (skillTrackingInstallations.has(pi)) return;
	skillTrackingInstallations.add(pi);

	pi.on("tool_call", (event) => {
		if (event?.toolName !== "skill") return;
		const input = event.input as { name?: unknown } | undefined;
		const name = typeof input?.name === "string" ? input.name : null;
		if (!name) return;
		trackInvokedSkill(name);
	});
}

function readSkillContent(filePath: string): string | null {
	let raw: string;
	try {
		raw = readFileSync(filePath, "utf-8");
	} catch {
		return null;
	}
	const content = stripFrontmatter(raw).trim();
	return content.length > 0 ? content : null;
}

function buildSkillBlock(name: string, content: string): string {
	const escapeXml = (value: string): string =>
		value
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;")
			.replace(/'/g, "&apos;");
	return `<skill name="${escapeXml(name)}">\n${content}\n</skill>`;
}

function formatTaskProgressSummary(snapshot: TaskProgressSnapshot): string | null {
	const tasks = snapshot.tasks ?? [];
	const total = tasks.filter((task) => task.status !== "deleted").length;
	if (total === 0) return null;
	const completed = tasks.filter((task) => task.status === "completed").length;
	return `${completed}/${total} tasks completed`;
}

function renderCompactTaskProgressLines(snapshot: TaskProgressSnapshot, theme: TaskProgressTheme): string[] {
	if (snapshot.tasks.length === 0 && !snapshot.goal) return [];
	const lines: string[] = [];
	if (snapshot.goal) {
		lines.push(`${theme.fg("dim", "Goal")}  ${snapshot.goal}`);
	}
	if (snapshot.tasks.length === 0) return lines;

	const markers: Record<string, string> = {
		completed: "✓",
		active: "→",
		pending: "☐",
		deleted: "✕",
	};

	const preferredStart = snapshot.tasks.findIndex((task) => task.status === "active");
	const fallbackStart = snapshot.tasks.findIndex((task) => task.status === "pending");
	const start = preferredStart >= 0 ? preferredStart : fallbackStart >= 0 ? fallbackStart : 0;
	const WINDOW_SIZE = 3;

	for (let idx = start; idx < snapshot.tasks.length && lines.length < WINDOW_SIZE + (snapshot.goal ? 1 : 0); idx += 1) {
		const task = snapshot.tasks[idx];
		if (!task) continue;
		const marker = markers[task.status] ?? "•";
		const line = `[${task.index ?? idx}] ${marker} ${task.label}`;
		if (task.status === "active") {
			lines.push(`${theme.fg("accent", line)}`);
			continue;
		}
		if (task.status === "deleted") {
			lines.push(`${theme.fg("muted", line)}`);
			continue;
		}
		lines.push(theme.fg(task.status === "completed" ? "muted" : "dim", line));
	}

	return lines;
}

function formatTitle(title: string, tag: string): string {
	return `${title} [${tag}]`;
}

function shortSessionId(sessionId: string): string {
	return sessionId.replace(/-/g, "").slice(-4);
}

function getWorkspaceState(): WorkspaceState | null {
	const launchCwd = process.cwd();
	const worktreePath = process.env.BASECAMP_WORKTREE_DIR?.trim();
	return {
		launchCwd,
		repo: null,
		activeWorktree: worktreePath ? { path: worktreePath } : null,
		protectedRoot: null,
	};
}

function registerCatalogProvider(_provider: object): void {
	/* no-op in standalone mode */
}

function resolveModelAlias(alias: string): string | undefined {
	const aliases = loadModelAliasConfig();
	return aliases[alias];
}

function buildBasecampExtensionRoot(): string {
	return path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
}

export function createLocalPiSwarmDependencies(
	basecampExtensionRoot = buildBasecampExtensionRoot(),
): PiSwarmDependencies {
	return {
		basecampExtensionRoot,
		registerCatalogProvider,
		resolveModelAlias,
		hasInvokedSkill,
		getWorkspaceState,
		readSkillContent,
		buildSkillBlock,
		formatTaskProgressSummary,
		renderCompactTaskProgressLines,
		formatTitle,
		shortSessionId,
	};
}
