/**
 * Custom footer — replaces pi's default footer with a cleaner layout.
 *
 * Single-line layout:
 *   Left:  git branch + active skills
 *   Right: context% + model
 *
 * Extension statuses (agent progress, etc.) render as a second line
 * only when present.
 *
 * Skills are tracked by intercepting `read` tool calls for SKILL.md
 * files that match known skill locations from pi's skill registry.
 */

import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { isToolCallEventType } from "@mariozechner/pi-coding-agent";
import { truncateToWidth, visibleWidth } from "@mariozechner/pi-tui";

// ============================================================================
// Skill Tracking
// ============================================================================

/** Set of skill names invoked this session (order-preserving via array). */
const invokedSkills: string[] = [];

/** Map of SKILL.md path → skill name, built at session start. */
let skillPathMap = new Map<string, string>();

/** Render callback — set when footer is active, called to trigger re-render. */
let requestRender: (() => void) | null = null;

function trackSkillRead(filePath: string): void {
	const skillName = skillPathMap.get(filePath);
	if (skillName && !invokedSkills.includes(skillName)) {
		invokedSkills.push(skillName);
		requestRender?.();
	}
}

// ============================================================================
// Token Formatting
// ============================================================================

function formatTokens(count: number): string {
	if (count < 1000) return count.toString();
	if (count < 10_000) return `${(count / 1000).toFixed(1)}k`;
	if (count < 1_000_000) return `${Math.round(count / 1000)}k`;
	return `${(count / 1_000_000).toFixed(1)}M`;
}

// ============================================================================
// Registration
// ============================================================================

export function registerFooter(pi: ExtensionAPI): void {
	let ctx: ExtensionContext | null = null;

	// --- Build skill path map + set footer at session start ---
	pi.on("session_start", (_event, sessionCtx) => {
		ctx = sessionCtx;

		const skills = pi.getCommands().filter((c) => c.source === "skill");

		skillPathMap = new Map();
		for (const skill of skills) {
			const name = skill.name.replace(/^skill:/, "");
			skillPathMap.set(skill.sourceInfo.path, name);
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

					// --- Left side: branch + skills ---
					const parts: string[] = [];

					const branch = footerData.getGitBranch();
					if (branch) {
						parts.push(fg("muted", branch));
					}

					if (invokedSkills.length > 0) {
						const skillList = invokedSkills.map((s) => fg("accent", s)).join(fg("dim", ", "));
						parts.push(fg("dim", "skills: ") + skillList);
					}

					const left = parts.join(fg("dim", " · "));

					// --- Right side: context% + model ---
					const rightParts: string[] = [];

					if (ctx) {
						const usage = ctx.getContextUsage();
						if (usage?.percent !== null && usage?.percent !== undefined) {
							let ctxStr: string;
							if (usage.percent > 90) {
								ctxStr = fg("error", `ctx:${usage.percent.toFixed(0)}%`);
							} else if (usage.percent > 70) {
								ctxStr = fg("warning", `ctx:${usage.percent.toFixed(0)}%`);
							} else {
								ctxStr = fg("dim", `ctx:${usage.percent.toFixed(0)}%`);
							}
							rightParts.push(ctxStr);
						}

						// Token stats
						let totalInput = 0;
						let totalOutput = 0;
						let totalCost = 0;
						for (const entry of ctx.sessionManager.getEntries()) {
							if (entry.type === "message" && entry.message.role === "assistant") {
								const u = (entry.message as { usage: { input: number; output: number; cost: { total: number } } })
									.usage;
								totalInput += u.input;
								totalOutput += u.output;
								totalCost += u.cost.total;
							}
						}
						if (totalInput > 0) {
							rightParts.push(fg("dim", `↑${formatTokens(totalInput)} ↓${formatTokens(totalOutput)}`));
						}
						if (totalCost > 0) {
							rightParts.push(fg("dim", `$${totalCost.toFixed(3)}`));
						}
					}

					const model = ctx?.model?.id ?? "no-model";
					rightParts.push(fg("dim", model));

					const right = rightParts.join(fg("dim", " "));

					// --- Layout ---
					const leftWidth = visibleWidth(left);
					const rightWidth = visibleWidth(right);
					const minGap = 2;

					let line: string;
					if (leftWidth + minGap + rightWidth <= width) {
						const pad = " ".repeat(width - leftWidth - rightWidth);
						line = left + pad + right;
					} else if (leftWidth + minGap + rightWidth > width && rightWidth < width) {
						const available = width - rightWidth - minGap;
						const truncLeft = available > 0 ? truncateToWidth(left, available, fg("dim", "…")) : "";
						const pad = " ".repeat(Math.max(0, width - visibleWidth(truncLeft) - rightWidth));
						line = truncLeft + pad + right;
					} else {
						line = truncateToWidth(`${left}  ${right}`, width, fg("dim", "…"));
					}

					const lines = [line];

					// --- Extension statuses (agent progress, etc.) ---
					const statuses = footerData.getExtensionStatuses();
					if (statuses.size > 0) {
						const sorted = Array.from(statuses.entries())
							.sort(([a], [b]) => a.localeCompare(b))
							.map(([, text]) => text.replace(/[\r\n\t]/g, " ").trim());
						lines.push(truncateToWidth(sorted.join("  "), width, fg("dim", "…")));
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

	// --- Track skill reads via tool_call events ---
	pi.on("tool_call", async (event) => {
		if (isToolCallEventType("read", event)) {
			trackSkillRead(event.input.path);
		}
	});
}
