/**
 * Custom footer — replaces pi's default footer.
 *
 * Three-line layout:
 *   Line 1: cwd | worktree | branch ... cost + model
 *   Line 2: invoked skills ... context bar
 *   Line 3: agent statuses (only when active)
 *
 * Skills are tracked by the skill tool itself (skill.ts). The footer
 * re-renders on `tool_result` events to pick up newly loaded skills.
 */

import { existsSync, type FSWatcher, readFileSync, statSync, watch } from "node:fs";
import * as os from "node:os";
import { dirname, join, resolve } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { truncateToWidth, visibleWidth } from "@mariozechner/pi-tui";
import { getState } from "./session";
import { getInvokedSkills } from "./skill-tracker.ts";

type ThemeFg = (color: Parameters<import("@mariozechner/pi-coding-agent").Theme["fg"]>[0], text: string) => string;
let requestRender: (() => void) | null = null;

/**
 * Worktree branch watcher — pi's FooterDataProvider watches the main repo's
 * HEAD, not the worktree's. We run our own watcher on the worktree's HEAD
 * so the footer shows the actual branch.
 */
let worktreeBranchCache: string | null = null;
let worktreeHeadWatcher: FSWatcher | null = null;
let worktreeWatcherInitialized = false;

function resolveWorktreeHeadPath(worktreeDir: string): string | null {
	try {
		const gitPath = join(worktreeDir, ".git");
		if (!existsSync(gitPath)) return null;
		const stat = statSync(gitPath);
		if (stat.isDirectory()) return join(gitPath, "HEAD");
		const content = readFileSync(gitPath, "utf8").trim();
		if (!content.startsWith("gitdir: ")) return null;
		const gitDir = resolve(worktreeDir, content.slice(8).trim());
		const headPath = join(gitDir, "HEAD");
		return existsSync(headPath) ? headPath : null;
	} catch {
		return null;
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

function initWorktreeWatcher(worktreeDir: string): void {
	if (worktreeWatcherInitialized) return;
	worktreeWatcherInitialized = true;

	const headPath = resolveWorktreeHeadPath(worktreeDir);
	if (!headPath) return;

	worktreeBranchCache = readBranchFromHead(headPath);

	try {
		worktreeHeadWatcher = watch(dirname(headPath), (_event, filename) => {
			if (!filename || filename.toString() === "HEAD") {
				const next = readBranchFromHead(headPath);
				if (next !== worktreeBranchCache) {
					worktreeBranchCache = next;
					requestRender?.();
				}
			}
		});
	} catch {
		// watch failed — fall back to static cache
	}
}

function disposeWorktreeWatcher(): void {
	worktreeHeadWatcher?.close();
	worktreeHeadWatcher = null;
	worktreeWatcherInitialized = false;
	worktreeBranchCache = null;
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

export function registerFooter(pi: ExtensionAPI): void {
	let ctx: ExtensionContext | null = null;

	pi.on("session_start", (_event, sessionCtx) => {
		ctx = sessionCtx;

		// Replace default footer
		if (!sessionCtx.hasUI) return;

		sessionCtx.ui.setFooter((tui, theme, footerData) => {
			requestRender = () => tui.requestRender();
			const unsub = footerData.onBranchChange(() => tui.requestRender());

			return {
				invalidate() {},
				render(width: number): string[] {
					const fg = theme.fg.bind(theme);
					const state = getState();

					if (state.worktreeDir) initWorktreeWatcher(state.worktreeDir);

					// ── Line 1: cwd | worktree | branch ... cost + model ──
					const l1Left = buildLocationSegment(fg, state, footerData);
					const l1Right = buildModelSegment(fg, ctx, pi);
					const line1 = layoutLine(l1Left, l1Right, width, fg);

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

					// ── Line 3: agent statuses (conditional) ──
					const statuses = footerData.getExtensionStatuses();
					if (statuses.size > 0) {
						const sorted = Array.from(statuses.entries())
							.sort(([a], [b]) => a.localeCompare(b))
							.map(([, text]) => text.replace(/[\r\n\t]/g, " ").trim());
						lines.push(truncateToWidth(sorted.join(fg("dim", "  ")), width, fg("dim", "…")));
					}

					return lines;
				},

				dispose() {
					unsub();
					disposeWorktreeWatcher();
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

function buildLocationSegment(
	fg: ThemeFg,
	state: ReturnType<typeof getState>,
	footerData: { getGitBranch(): string | null },
): string {
	const parts: string[] = [];
	parts.push(fg("dim", shortenPath(state.primaryDir)));

	if (state.worktreeLabel) {
		parts.push(fg("warning", `⌥ ${state.worktreeLabel}`));
	} else {
		parts.push(fg("muted", "⌥ main"));
	}

	const branch = state.worktreeDir ? worktreeBranchCache : footerData.getGitBranch();
	if (branch) {
		parts.push(fg("accent", `⎇ ${branch}`));
	}

	return parts.join(fg("dim", "  "));
}

function buildModelSegment(fg: ThemeFg, ctx: ExtensionContext | null, pi: ExtensionAPI): string {
	const parts: string[] = [];
	let totalCost = 0;

	if (ctx) {
		for (const entry of ctx.sessionManager.getEntries()) {
			if (entry.type === "message" && entry.message.role === "assistant") {
				const u = (entry.message as { usage: { cost: { total: number } } }).usage;
				totalCost += u.cost.total;
			}
		}
	}

	const modelId = ctx?.model?.id ?? "no-model";
	if (totalCost > 0) {
		parts.push([fg("muted", `$${totalCost.toFixed(2)}`), fg("dim", "·"), fg("text", modelId)].join(" "));
	} else {
		parts.push(fg("text", modelId));
	}

	if (ctx?.model?.reasoning) {
		parts.push(fg("muted", pi.getThinkingLevel()));
	}

	return parts.join(fg("dim", "  "));
}
