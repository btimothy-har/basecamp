import type { ExtensionUIContext, Theme } from "@earendil-works/pi-coding-agent";
import { DynamicBorder, getSelectListTheme } from "@earendil-works/pi-coding-agent";
import { Container, Editor, type EditorTheme, getKeybindings, matchesKey, Spacer, Text } from "@earendil-works/pi-tui";
import type { Finding } from "./findings.ts";

export interface AnnotateResult {
	cancelled: boolean;
	reactions: (string | null)[];
}

export function findingSummaryLines(finding: Finding, index: number, total: number): string[] {
	return [
		`Finding ${index + 1} of ${total}`,
		`[${finding.severity}] [${finding.dimension}]  ${finding.file ?? "(no file)"}:${finding.lineStart ?? "?"}`,
		finding.title,
		"",
		finding.detail,
		"",
		`Fix: ${finding.remediation ?? "—"}`,
	];
}

export function responseDisplayLines(finding: Finding): string[] {
	const body = finding.response?.trim();
	return ["Author response:", body || "—"];
}

export function buildReactions(findings: Finding[], drafts: Map<number, string>): (string | null)[] {
	return findings.map((_finding, index) => {
		const text = drafts.get(index)?.trim();
		return text ? text : null;
	});
}

function matchesInputSubmit(data: string): boolean {
	return getKeybindings().matches(data, "tui.input.submit");
}

function matchesInputTab(data: string): boolean {
	return getKeybindings().matches(data, "tui.input.tab");
}

function matchesSelectCancel(data: string): boolean {
	return getKeybindings().matches(data, "tui.select.cancel");
}

function colorSummaryLines(lines: readonly string[], theme: Theme): string[] {
	const colored = [...lines];
	colored[0] = theme.fg("accent", theme.bold(colored[0] ?? ""));
	colored[1] = theme.fg("dim", colored[1] ?? "");
	colored[2] = theme.bold(colored[2] ?? "");
	const fixIndex = colored.length - 1;
	colored[fixIndex] = theme.fg("warning", colored[fixIndex] ?? "");
	return colored;
}

function colorResponseLines(lines: readonly string[], theme: Theme): string[] {
	const colored = [...lines];
	colored[0] = theme.fg("muted", colored[0] ?? "");
	colored[1] = theme.fg("dim", colored[1] ?? "");
	return colored;
}

export async function annotateFindings(
	ui: Pick<ExtensionUIContext, "custom">,
	findings: Finding[],
): Promise<AnnotateResult> {
	if (findings.length === 0) return { cancelled: false, reactions: [] };

	const drafts = new Map<number, string>();

	return ui.custom<AnnotateResult>((tui, theme, _keybindings, done) => {
		let current = 0;
		let editing = false;

		const border = new DynamicBorder((s: string) => theme.fg("border", s));
		const title = new Text(theme.fg("accent", theme.bold("Code Review Reactions")), 1, 0);
		const summary = new Text("", 1, 0);
		const responseText = new Text("", 1, 0);
		const reactionLabel = new Text("", 1, 0);
		const hint = new Text("", 1, 0);

		const editorTheme: EditorTheme = {
			borderColor: (s: string) => theme.fg("dim", s),
			selectList: getSelectListTheme(),
		};
		const reactionEditor = new Editor(tui, editorTheme, { paddingX: 0 });
		reactionEditor.disableSubmit = false;
		reactionEditor.focused = false;

		const container = new Container();
		container.addChild(border);
		container.addChild(title);
		container.addChild(new Spacer(1));
		container.addChild(summary);
		container.addChild(new Spacer(1));
		container.addChild(responseText);
		container.addChild(new Spacer(1));
		container.addChild(reactionLabel);
		container.addChild(reactionEditor);
		container.addChild(new Spacer(1));
		container.addChild(hint);
		container.addChild(border);

		function commitCurrentDraft(): void {
			drafts.set(current, reactionEditor.getText());
		}

		function result(cancelled: boolean): AnnotateResult {
			commitCurrentDraft();
			return { cancelled, reactions: buildReactions(findings, drafts) };
		}

		function updateView(): void {
			const finding = findings[current]!;
			summary.setText(colorSummaryLines(findingSummaryLines(finding, current, findings.length), theme).join("\n"));
			responseText.setText(colorResponseLines(responseDisplayLines(finding), theme).join("\n"));
			reactionLabel.setText(theme.fg("accent", "Your reaction (optional):"));
			if (reactionEditor.getText() !== (drafts.get(current) ?? "")) {
				reactionEditor.setText(drafts.get(current) ?? "");
			}
			reactionEditor.focused = editing;
			const editHint = "[Enter: Save reaction]  [Esc: Back to list]";
			const navHint = "[←/→ or p/n: Prev/Next]  [Tab or Enter: Edit reaction]  [s: Submit]  [Esc: Cancel]";
			hint.setText(theme.fg("dim", editing ? editHint : navHint));
		}

		function setEditing(nextEditing: boolean): void {
			if (!nextEditing) commitCurrentDraft();
			editing = nextEditing;
			reactionEditor.focused = editing;
			updateView();
			container.invalidate();
		}

		function navigate(delta: number): void {
			const next = current + delta;
			if (next < 0 || next >= findings.length) return;
			commitCurrentDraft();
			current = next;
			editing = false;
			updateView();
			container.invalidate();
		}

		reactionEditor.onSubmit = (value: string) => {
			drafts.set(current, value);
			setEditing(false);
		};

		updateView();

		return {
			render: (width: number) => container.render(width),
			invalidate: () => container.invalidate(),
			handleInput: (data: string) => {
				if (editing) {
					if (matchesSelectCancel(data)) {
						setEditing(false);
						return;
					}
					reactionEditor.handleInput(data);
					container.invalidate();
					return;
				}

				if (matchesSelectCancel(data)) {
					done(result(true));
					return;
				}

				if (matchesKey(data, "left") || matchesKey(data, "p") || matchesKey(data, "shift+p")) {
					navigate(-1);
					return;
				}
				if (matchesKey(data, "right") || matchesKey(data, "n") || matchesKey(data, "shift+n")) {
					navigate(1);
					return;
				}
				if (matchesInputTab(data) || matchesInputSubmit(data)) {
					setEditing(true);
					return;
				}
				if (matchesKey(data, "s") || matchesKey(data, "shift+s")) {
					done(result(false));
				}
			},
		};
	});
}
