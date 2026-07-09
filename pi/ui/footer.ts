/**
 * Custom footer — replaces pi's default footer.
 *
 * Three-line layout:
 *   Line 1: cwd | worktree | branch ... model
 *   Line 2: invoked skills ... context bar
 *   Line 3: extension statuses
 *
 * Skills are tracked by the skill tool itself (skill.ts). The footer
 * re-renders on `tool_result` events to pick up newly loaded skills.
 */

import { existsSync, type FSWatcher, readFileSync, statSync, watch } from "node:fs";
import * as os from "node:os";
import { dirname, join, resolve } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";
import { type AgentMode, getAgentMode, onAgentModeChange } from "#core/agent-mode/index.ts";
import { getInvokedSkills } from "#core/platform/skill-tracker.ts";
import { getWorkspaceService, getWorkspaceState, type WorkspaceState } from "#core/platform/workspace.ts";
import { getModeLabel } from "./mode.ts";

type ThemeFg = (color: Parameters<import("@earendil-works/pi-coding-agent").Theme["fg"]>[0], text: string) => string;

interface LocationLineParts {
	mode: string | null;
	cwd: string;
	metadata: string[];
}

let requestRender: (() => void) | null = null;

/**
 * Branch watcher for the exact directory represented in the footer.
 * Pi's FooterDataProvider is created from Pi's cwd; Basecamp can later override
 * the effective cwd/worktree, so we resolve and watch HEAD ourselves.
 */
let branchCache: string | null = null;
let branchHeadWatcher: FSWatcher | null = null;
let branchWatcherTarget: string | null = null;

function resolveGitHeadPath(startDir: string): string | null {
	let dir = resolve(startDir);
	while (true) {
		try {
			const gitPath = join(dir, ".git");
			if (existsSync(gitPath)) {
				const stat = statSync(gitPath);
				if (stat.isDirectory()) {
					const headPath = join(gitPath, "HEAD");
					return existsSync(headPath) ? headPath : null;
				}
				const content = readFileSync(gitPath, "utf8").trim();
				if (!content.startsWith("gitdir: ")) return null;
				const gitDir = resolve(dir, content.slice(8).trim());
				const headPath = join(gitDir, "HEAD");
				return existsSync(headPath) ? headPath : null;
			}
		} catch {
			return null;
		}

		const parent = dirname(dir);
		if (parent === dir) return null;
		dir = parent;
	}
}

function readBranchFromHead(headPath: string): string | null {
	try {
		const content = readFileSync(headPath, "utf8").trim();
		if (content.startsWith("ref: refs/heads/")) return content.slice(16);
		return "detached";
	} catch {
		return null;
	}
}

function syncBranchWatcher(targetDir: string): void {
	const normalizedTarget = resolve(targetDir);
	if (branchWatcherTarget === normalizedTarget) return;

	disposeBranchWatcher();
	branchWatcherTarget = normalizedTarget;

	const headPath = resolveGitHeadPath(normalizedTarget);
	if (!headPath) return;

	branchCache = readBranchFromHead(headPath);

	try {
		branchHeadWatcher = watch(dirname(headPath), (_event, filename) => {
			if (!filename || filename.toString() === "HEAD") {
				const next = readBranchFromHead(headPath);
				if (next !== branchCache) {
					branchCache = next;
					requestRender?.();
				}
			}
		});
	} catch {
		// watch failed — fall back to static cache
	}
}

function resolveFooterBranch(targetDir: string, fallbackBranch: string | null): string | null {
	syncBranchWatcher(targetDir);
	return branchCache ?? fallbackBranch;
}

function disposeBranchWatcher(): void {
	branchHeadWatcher?.close();
	branchHeadWatcher = null;
	branchWatcherTarget = null;
	branchCache = null;
}

function getFooterEffectiveCwd(workspace: WorkspaceState | null): string {
	const service = getWorkspaceService();
	if (service && workspace) {
		try {
			return service.getEffectiveCwd();
		} catch {
			// Fall through to workspace/process fallback
		}
	}
	return workspace?.effectiveCwd ?? process.cwd();
}

function shortenPath(p: string): string {
	const home = os.homedir();
	if (p.startsWith(home)) p = `~${p.slice(home.length)}`;

	const parts = p.split("/");
	if (parts.length <= 3) return p;

	const shortened = parts.slice(0, -1).map((seg, i) => (i === 0 ? seg : seg[0] || seg));
	shortened.push(parts.at(-1)!);
	return shortened.join("/");
}

/** Render context usage: ctx: 45.2k / 200k (23%) */
function renderContextUsage(fg: ThemeFg, tokens: number | null, window: number, percent: number): string {
	const tokStr = tokens !== null ? formatTokens(tokens) : "?";
	const winStr = formatTokens(window);
	const pctStr = `${percent.toFixed(0)}%`;

	let color: Parameters<ThemeFg>[0] = "dim";
	if (percent > 70) color = "error";
	else if (percent > 50) color = "warning";
	else if (tokens !== null && tokens > 100_000) color = "border";

	return fg(color, `ctx: ${tokStr} / ${winStr} (${pctStr})`);
}

function formatTokens(count: number): string {
	if (count < 1000) return count.toString();
	if (count < 10_000) return `${(count / 1000).toFixed(1)}k`;
	if (count < 1_000_000) return `${Math.round(count / 1000)}k`;
	return `${(count / 1_000_000).toFixed(1)}M`;
}

/** Join left and right with padding, truncating left if needed. */
function layoutLine(left: string, right: string, width: number, fg: ThemeFg): string {
	const lw = visibleWidth(left);
	const rw = visibleWidth(right);
	const minGap = 2;

	if (lw + minGap + rw <= width) {
		return left + " ".repeat(width - lw - rw) + right;
	}

	const available = width - rw - minGap;
	if (available > 0) {
		const truncLeft = truncateToWidth(left, available, fg("dim", "…"));
		const pad = " ".repeat(Math.max(0, width - visibleWidth(truncLeft) - rw));
		return truncLeft + pad + right;
	}

	return truncateToWidth(`${left}  ${right}`, width, fg("dim", "…"));
}

function joinSegments(parts: Array<string | null | undefined>, fg: ThemeFg): string {
	return parts.filter((part): part is string => Boolean(part)).join(fg("dim", "  "));
}

function layoutLocationLine(location: LocationLineParts, right: string, width: number, fg: ThemeFg): string {
	const fullLeft = joinSegments([location.mode, location.cwd, ...location.metadata], fg);
	if (visibleWidth(fullLeft) + 2 + visibleWidth(right) <= width) return layoutLine(fullLeft, right, width, fg);

	const maxRightWidth = visibleWidth(right);
	const rightCandidates = [
		right,
		maxRightWidth > 32 ? truncateToWidth(right, 32, fg("dim", "…")) : right,
		maxRightWidth > 20 ? truncateToWidth(right, 20, fg("dim", "…")) : right,
		"",
	];

	for (const rightCandidate of new Set(rightCandidates)) {
		for (let cwdWidth = visibleWidth(location.cwd); cwdWidth >= 0; cwdWidth--) {
			const cwd = cwdWidth > 0 ? truncateToWidth(location.cwd, cwdWidth, fg("dim", "…")) : null;
			const left = joinSegments([location.mode, cwd, ...location.metadata], fg);
			if (!left && !rightCandidate) continue;
			if (visibleWidth(left) + 2 + visibleWidth(rightCandidate) <= width) {
				return layoutLine(left, rightCandidate, width, fg);
			}
		}
	}

	return truncateToWidth(
		joinSegments([location.mode, location.cwd, ...location.metadata, right], fg),
		width,
		fg("dim", "…"),
	);
}

export function registerFooter(pi: ExtensionAPI): void {
	let ctx: ExtensionContext | null = null;

	pi.on("session_start", (_event, sessionCtx) => {
		ctx = sessionCtx;

		// Replace default footer
		if (!sessionCtx.hasUI) return;

		sessionCtx.ui.setFooter((tui, theme, footerData) => {
			requestRender = () => tui.requestRender();
			const unsubBranch = footerData.onBranchChange(() => tui.requestRender());
			const unsubMode = onAgentModeChange(() => tui.requestRender());

			return {
				invalidate() {},
				render(width: number): string[] {
					const fg = theme.fg.bind(theme);
					const workspace = getWorkspaceState();
					const effectiveCwd = getFooterEffectiveCwd(workspace);

					// ── Line 1: cwd | worktree | branch ... model ──
					// Keep mode/worktree/branch visible; truncate cwd/model first.
					const location = buildLocationParts(fg, workspace, effectiveCwd, footerData);
					const l1Right = buildModelSegment(fg, ctx, pi);
					const line1 = layoutLocationLine(location, l1Right, width, fg);

					// ── Line 2: skills ... context bar ──
					let l2Left = "";
					const skills = getInvokedSkills();
					if (skills.length > 0) {
						const skillList = skills.map((s) => fg("accent", s)).join(fg("dim", ", "));
						l2Left = `${fg("muted", "📖 ")}${skillList}`;
					}

					let l2Right = "";
					if (ctx) {
						const usage = ctx.getContextUsage();
						if (usage?.percent !== null && usage?.percent !== undefined) {
							l2Right = renderContextUsage(fg, usage.tokens, usage.contextWindow, usage.percent);
						}
					}

					const line2 = layoutLine(l2Left, l2Right, width, fg);
					const lines = [line1, line2];

					const statuses = footerData.getExtensionStatuses();
					const line3Parts = Array.from(statuses.entries())
						.sort(([a], [b]) => a.localeCompare(b))
						.map(([, text]) => text.replace(/[\r\n\t]/g, " ").trim())
						.filter((text) => text.length > 0);
					lines.push(truncateToWidth(line3Parts.join(fg("dim", "  ")), width, fg("dim", "…")));

					return lines;
				},

				dispose() {
					unsubBranch();
					unsubMode();
					disposeBranchWatcher();
					requestRender = null;
				},
			};
		});
	});

	pi.on("tool_result", async (event) => {
		if (event.toolName === "skill" && !event.isError) {
			requestRender?.();
		}
	});
}

function buildLocationParts(
	fg: ThemeFg,
	workspace: WorkspaceState | null,
	effectiveCwd: string,
	footerData: { getGitBranch(): string | null },
): LocationLineParts {
	const metadata: string[] = [];
	const activeWorktree = workspace?.activeWorktree ?? null;

	if (activeWorktree) {
		metadata.push(fg("warning", `⌥ ${activeWorktree.label}`));
		if (workspace?.unsafeEdit) metadata.push(fg("error", "⚠ unsafe-edit"));
	} else if (workspace?.unsafeEdit) {
		metadata.push(fg("error", "⌥ unsafe-edit"));
	} else {
		metadata.push(fg("muted", "⌥ protected"));
	}

	const branchTarget = activeWorktree?.path ?? effectiveCwd;
	const branch = resolveFooterBranch(branchTarget, activeWorktree?.branch ?? footerData.getGitBranch());
	if (branch) metadata.push(fg("accent", `⎇ ${branch}`));

	return {
		mode: buildModeSegment(fg, getAgentMode()),
		cwd: fg("dim", shortenPath(effectiveCwd)),
		metadata,
	};
}

function buildModeSegment(fg: ThemeFg, mode: AgentMode): string | null {
	const style = getModeLabel(mode);
	return style ? fg(style.color, style.label) : null;
}

function buildModelSegment(fg: ThemeFg, ctx: ExtensionContext | null, pi: ExtensionAPI): string {
	const parts = [fg("text", ctx?.model?.id ?? "no-model")];

	if (ctx?.model?.reasoning) {
		parts.push(fg("muted", pi.getThinkingLevel()));
	}

	return parts.join(fg("dim", "  "));
}
