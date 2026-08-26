import { copyToClipboard, type ExtensionCommandContext, type Theme } from "@earendil-works/pi-coding-agent";
import { type Component, matchesKey, truncateToWidth, visibleWidth, wrapTextWithAnsi } from "@earendil-works/pi-tui";

const RESERVED_TERMINAL_ROWS = 10;

type ViewerTheme = Pick<Theme, "bold" | "fg">;
type CopyText = (text: string) => Promise<void>;

export interface SystemPromptPreview {
	prompt: string;
	inactive: boolean;
}

export function escapePromptForDisplay(prompt: string): string {
	const display: string[] = [];
	for (const character of prompt) {
		const code = character.codePointAt(0) ?? 0;
		const isControl = code <= 9 || (code >= 11 && code <= 31) || (code >= 127 && code <= 159);
		if (!isControl) {
			display.push(character);
		} else if (code === 9) {
			display.push("\\t");
		} else if (code === 13) {
			display.push("\\r");
		} else {
			display.push(`\\x${code.toString(16).padStart(2, "0")}`);
		}
	}
	return display.join("");
}

function fitLine(text: string, width: number): string {
	const fitted = truncateToWidth(text, Math.max(1, width));
	return fitted + " ".repeat(Math.max(0, width - visibleWidth(fitted)));
}

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

export class SystemPromptViewer implements Component {
	private offset = 0;
	private pageSize = 1;
	private maxOffset = 0;
	private wrappedWidth = 0;
	private wrappedLines: string[] = [];
	private readonly displayPrompt: string;
	private readonly characterCount: number;
	private readonly sourceLines: number;
	private readonly preview: SystemPromptPreview;
	private readonly theme: ViewerTheme;
	private readonly terminalRows: () => number;
	private readonly requestRender: () => void;
	private readonly close: () => void;
	private readonly copy: () => void;

	constructor(
		preview: SystemPromptPreview,
		theme: ViewerTheme,
		terminalRows: () => number,
		requestRender: () => void,
		close: () => void,
		copy: () => void,
	) {
		this.preview = preview;
		this.theme = theme;
		this.terminalRows = terminalRows;
		this.requestRender = requestRender;
		this.close = close;
		this.copy = copy;
		this.displayPrompt = escapePromptForDisplay(preview.prompt);
		this.characterCount = Array.from(preview.prompt).length;
		this.sourceLines = preview.prompt.split("\n").length;
	}

	invalidate(): void {}

	render(width: number): string[] {
		const safeWidth = Math.max(1, width);
		const padding = safeWidth > 2 ? 1 : 0;
		const contentWidth = Math.max(1, safeWidth - padding * 2);
		if (contentWidth !== this.wrappedWidth) {
			const wrapped = wrapTextWithAnsi(this.displayPrompt, contentWidth);
			this.wrappedLines = wrapped.length > 0 ? wrapped : [""];
			this.wrappedWidth = contentWidth;
		}
		const lines = this.wrappedLines;

		this.pageSize = Math.max(1, Math.min(lines.length, this.terminalRows() - RESERVED_TERMINAL_ROWS));
		this.maxOffset = Math.max(0, lines.length - this.pageSize);
		this.offset = Math.min(this.offset, this.maxOffset);

		const firstVisible = this.offset + 1;
		const lastVisible = Math.min(lines.length, this.offset + this.pageSize);
		const status = this.preview.inactive
			? this.theme.fg("warning", "Inactive: a Pi custom system prompt bypasses Basecamp replacement")
			: this.theme.fg("success", "Fresh Basecamp compilation");
		const margin = " ".repeat(padding);
		const body = lines
			.slice(this.offset, this.offset + this.pageSize)
			.map((line) => fitLine(`${margin}${line}${margin}`, safeWidth));

		return [
			this.theme.fg("border", "─".repeat(safeWidth)),
			fitLine(` ${this.theme.fg("accent", this.theme.bold("System Prompt"))}`, safeWidth),
			fitLine(` ${status}`, safeWidth),
			fitLine(` ${this.characterCount} chars · ${this.sourceLines} source lines`, safeWidth),
			...body,
			fitLine(` Visual lines ${firstVisible}-${lastVisible} of ${lines.length}`, safeWidth),
			fitLine(" ↑↓ line  PgUp/PgDn page  Home/End  c copy  Esc close", safeWidth),
			this.theme.fg("border", "─".repeat(safeWidth)),
		];
	}

	handleInput(data: string): void {
		if (matchesKey(data, "escape")) {
			this.close();
			return;
		}
		if (matchesKey(data, "c") || matchesKey(data, "shift+c")) {
			this.copy();
			return;
		}
		if (matchesKey(data, "home")) {
			this.moveTo(0);
		} else if (matchesKey(data, "end")) {
			this.moveTo(this.maxOffset);
		} else if (matchesKey(data, "up")) {
			this.moveTo(this.offset - 1);
		} else if (matchesKey(data, "down")) {
			this.moveTo(this.offset + 1);
		} else if (matchesKey(data, "pageUp")) {
			this.moveTo(this.offset - this.pageSize);
		} else if (matchesKey(data, "pageDown")) {
			this.moveTo(this.offset + this.pageSize);
		}
	}

	private moveTo(offset: number): void {
		const next = Math.max(0, Math.min(this.maxOffset, offset));
		if (next === this.offset) return;
		this.offset = next;
		this.requestRender();
	}
}

export async function showSystemPromptPreview(
	preview: SystemPromptPreview,
	ctx: ExtensionCommandContext,
	copyText: CopyText = copyToClipboard,
): Promise<void> {
	await ctx.ui.custom<void>((tui, theme, _keybindings, done) => {
		const copy = (): void => {
			void copyText(preview.prompt)
				.then(() => ctx.ui.notify("System prompt copied.", "info"))
				.catch((error) => ctx.ui.notify(`Could not copy system prompt: ${errorMessage(error)}`, "error"));
		};

		return new SystemPromptViewer(
			preview,
			theme,
			() => tui.terminal.rows,
			() => tui.requestRender(),
			() => done(undefined),
			copy,
		);
	});
}
