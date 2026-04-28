import type { ThemeColor } from "@mariozechner/pi-coding-agent";
import type { AgentMode } from "../runtime/mode";

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
	planning: { label: "[plan]", color: "warning" },
	supervisor: { label: "[supervisor]", color: "error" },
	executor: { label: "[exec]", color: "text" },
};

export function getModeColor(mode: AgentMode): ThemeColor {
	return MODE_STYLES[mode].color;
}

export function getModeLabel(mode: AgentMode): ModeLabelStyle | null {
	const style = MODE_STYLES[mode];
	return style.label ? { label: style.label, color: style.color } : null;
}
