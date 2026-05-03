import { CustomEditor, type ExtensionAPI, type KeybindingsManager, type Theme } from "@mariozechner/pi-coding-agent";
import type { EditorTheme, TUI } from "@mariozechner/pi-tui";
import { getAgentMode } from "../../../platform/session";
import { getModeColor } from "./mode-style";

type BorderColor = (text: string) => string;

class ModeAwareEditor extends CustomEditor {
	constructor(
		tui: TUI,
		theme: EditorTheme,
		keybindings: KeybindingsManager,
		private readonly currentTheme: () => Theme,
	) {
		super(tui, theme, keybindings);
	}

	override render(width: number): string[] {
		this.borderColor = getEditorBorderColor(this.currentTheme(), this.getText());
		return super.render(width);
	}
}

function getEditorBorderColor(theme: Theme, editorText: string): BorderColor {
	if (editorText.trimStart().startsWith("!")) return theme.getBashModeBorderColor();
	return (text) => theme.fg(getModeColor(getAgentMode()), text);
}

export function registerModeEditor(pi: ExtensionAPI): void {
	pi.on("session_start", (_event, ctx) => {
		if (!ctx.hasUI) return;

		ctx.ui.setEditorComponent((tui, theme, keybindings) => {
			return new ModeAwareEditor(tui, theme, keybindings, () => ctx.ui.theme);
		});
	});
}
