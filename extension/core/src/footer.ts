/**
 * Custom footer — replaces pi's default footer.
 *
 * Three-line layout:
 *   Line 1: cwd | worktree | branch ... cost + model
 *   Line 2: invoked skills ... context bar
 *   Line 3: agent statuses (only when active)
 *
 * Skills are tracked by intercepting `read` tool calls for SKILL.md
 * files that match known skill locations from pi's skill registry.
 */

import * as os from "node:os";
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { isToolCallEventType } from "@mariozechner/pi-coding-agent";
import { truncateToWidth, visibleWidth } from "@mariozechner/pi-tui";
import { getState } from "./session";

type ThemeFg = (color: Parameters<import("@mariozechner/pi-coding-agent").Theme["fg"]>[0], text: string) => string;

// ============================================================================
// Skill Tracking
// ============================================================================

const invokedSkills: string[] = [];
let skillPathMap = new Map<string, string>();
let requestRender: (() => void) | null = null;

function trackSkillRead(filePath: string): void {
	const skillName = skillPathMap.get(filePath);
	if (skillName && !invokedSkills.includes(skillName)) {
		invokedSkills.push(skillName);
		requestRender?.();
	}
}

// ============================================================================
// Formatting Helpers
// ============================================================================

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
	if (percent > 90) color = "error";
	else if (percent > 70) color = "warning";

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

// ============================================================================
// Registration
// ============================================================================

export function registerFooter(pi: ExtensionAPI): void {
	let ctx: ExtensionContext | null = null;

	pi.on("session_start", (_event, sessionCtx) => {
		ctx = sessionCtx;

		// Build skill path map
		const skills = pi.getCommands().filter((c) => c.source === "skill");
		skillPathMap = new Map();
		for (const skill of skills) {
			skillPathMap.set(skill.sourceInfo.path, skill.name.replace(/^skill:/, ""));
		}

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

					// ── Line 1: cwd | worktree | branch ... cost + model ──
					const l1Left = buildLocationSegment(fg, state, footerData, ctx);
					const l1Right = buildModelSegment(fg, ctx);
					const line1 = layoutLine(l1Left, l1Right, width, fg);

					// ── Line 2: skills ... context bar ──
					let l2Left = "";
					if (invokedSkills.length > 0) {
						const skillList = invokedSkills.map((s) => fg("accent", s)).join(fg("dim", ", "));
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
					requestRender = null;
				},
			};
		});
	});

	// Track skill reads
	pi.on("tool_call", async (event) => {
		if (isToolCallEventType("read", event)) {
			trackSkillRead(event.input.path);
		}
	});
}

// ============================================================================
// Line Builders
// ============================================================================

function buildLocationSegment(
	fg: ThemeFg,
	state: ReturnType<typeof getState>,
	footerData: { getGitBranch(): string | null },
	ctx: ExtensionContext | null,
): string {
	const parts: string[] = [];
	parts.push(fg("dim", shortenPath(ctx?.sessionManager.getCwd() ?? state.primaryDir)));

	if (state.worktreeLabel) {
		parts.push(fg("warning", `⌥ ${state.worktreeLabel}`));
	} else {
		parts.push(fg("muted", "⌥ main"));
	}

	const branch = footerData.getGitBranch();
	if (branch) {
		parts.push(fg("accent", `⎇ ${branch}`));
	}

	return parts.join(fg("dim", "  "));
}

function buildModelSegment(fg: ThemeFg, ctx: ExtensionContext | null): string {
	const parts: string[] = [];

	if (ctx) {
		let totalCost = 0;
		for (const entry of ctx.sessionManager.getEntries()) {
			if (entry.type === "message" && entry.message.role === "assistant") {
				const u = (entry.message as { usage: { cost: { total: number } } }).usage;
				totalCost += u.cost.total;
			}
		}
		if (totalCost > 0) {
			parts.push(fg("muted", `$${totalCost.toFixed(2)}`));
		}
	}

	parts.push(fg("text", ctx?.model?.id ?? "no-model"));
	return parts.join(fg("dim", "  "));
}
