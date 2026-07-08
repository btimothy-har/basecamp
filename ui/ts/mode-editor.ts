import { CustomEditor, type ExtensionAPI, type KeybindingsManager, type Theme } from "@earendil-works/pi-coding-agent";
import type { EditorTheme, TUI } from "@earendil-works/pi-tui";
import { getAgentMode } from "#core/session/agent-mode.ts";
import { getModeColor } from "./mode-style.ts";

type BorderColor = (text: string) => string;

class ModeAwareEditor extends CustomEditor {
	// Explicit field (not a constructor parameter property) so the module stays
	// loadable under strip-only TypeScript, which rejects non-erasable syntax.
	private readonly currentTheme: () => Theme;

	constructor(tui: TUI, theme: EditorTheme, keybindings: KeybindingsManager, currentTheme: () => Theme) {
		super(tui, theme, keybindings);
		this.currentTheme = currentTheme;
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
