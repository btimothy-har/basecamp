import type { ThemeColor } from "@earendil-works/pi-coding-agent";
import type { AgentMode } from "../agent-mode/index.ts";

type ModeStyle = {
	label: string | null;
	color: ThemeColor;
};

type ModeLabelStyle = {
	label: string;
	color: ThemeColor;
};

const MODE_STYLES: Record<AgentMode, ModeStyle> = {
	analysis: { label: "[analysis]", color: "syntaxType" },
	planning: { label: "[explore]", color: "warning" },
	work: { label: null, color: "text" },
	copilot: { label: "[copilot]", color: "syntaxType" },
};

export function getModeColor(mode: AgentMode): ThemeColor {
	return MODE_STYLES[mode].color;
}

export function getModeLabel(mode: AgentMode): ModeLabelStyle | null {
	const style = MODE_STYLES[mode];
	return style.label ? { label: style.label, color: style.color } : null;
}
