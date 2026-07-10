/**
 * Title — auto-extracted session title displayed below the editor.
 *
 * Right-aligned, compact, dimmed. Extracted in the background while no title
 * exists, or manually via `/title`. Context assembly lives in
 * user-context.ts (in #core); the LLM call and validation in llm/generate.ts.
 */

import type { ExtensionAPI, ExtensionContext, Theme } from "@earendil-works/pi-coding-agent";
import { visibleWidth } from "@earendil-works/pi-tui";
import { shortSessionId } from "../session/session-id.ts";
import { getCurrentSessionStateIfInitialized, updateCurrentSessionStateIfInitialized } from "../session/state/index.ts";
import { buildUserContext } from "../session/user-context.ts";
import { extractTitle, generateTitleCompletion, type TitleCompletion, validateTitleResponse } from "./llm/generate.ts";

export {
	type GenerateTitleCompletionOptions,
	generateTitleCompletion,
	type TitleCompletion,
	validateTitleResponse,
} from "./llm/generate.ts";

export interface RegisterTitleOptions {
	titleCompletion?: TitleCompletion;
}

function renderTitleWidget(
	title: string,
	fg: (color: Parameters<Theme["fg"]>[0], text: string) => string,
	bg: (color: Parameters<Theme["bg"]>[0], text: string) => string,
	bold: Theme["bold"],
	width: number,
): string[] {
	const text = fg("mdHeading", bold(title));
	const vw = visibleWidth(text);
	const pad = Math.max(0, width - vw - 1);
	const line = `${" ".repeat(pad)}${text} `;
	const linePad = Math.max(0, width - visibleWidth(line));
	return [bg("selectedBg", line + " ".repeat(linePad))];
}

export function formatTitle(title: string, tag: string): string {
	return `${title} [${tag}]`;
}

export function registerTitle(pi: ExtensionAPI, options: RegisterTitleOptions = {}): void {
	let ctx: ExtensionContext | null = null;
	let title: string | null = null;
	let sessionTag: string | null = null;
	let pendingTitle: AbortController | null = null;
	let turnCounter = 0;
	const completeTitle = options.titleCompletion ?? generateTitleCompletion;

	function updateWidget(): void {
		if (!ctx?.hasUI) return;

		if (!title) {
			ctx.ui.setWidget("basecamp-title", undefined, { placement: "belowEditor" });
			return;
		}

		ctx.ui.setWidget(
			"basecamp-title",
			(_tui, theme) => {
				const fg = theme.fg.bind(theme);
				const bg = theme.bg.bind(theme);
				const bold = theme.bold.bind(theme);
				let cachedLines: string[] | null = null;
				let cachedWidth = 0;

				return {
					invalidate() {
						cachedLines = null;
					},
					render(width: number): string[] {
						if (cachedLines && cachedWidth === width) return cachedLines;
						cachedWidth = width;
						const display = displayTitle();
						cachedLines = display ? renderTitleWidget(display, fg, bg, bold, width) : [];
						return cachedLines;
					},
				};
			},
			{ placement: "belowEditor" },
		);
	}

	/** Display title with session tag suffix. */
	function displayTitle(): string | null {
		if (!title) return null;
		return sessionTag ? formatTitle(title, sessionTag) : title;
	}

	function persistState(): void {
		updateCurrentSessionStateIfInitialized({ title });
	}

	function applyTitle(nextTitle: string): void {
		title = nextTitle;
		const display = displayTitle()!;
		pi.setSessionName(display);
		if (ctx?.hasUI) ctx.ui.setTitle(display);
		updateWidget();
		persistState();
	}

	function clearTitle(): void {
		title = null;
		updateWidget();
		persistState();
	}

	pi.registerCommand("title", {
		description: "Generate a session title from the conversation, or set one manually",
		handler: async (args, cmdCtx) => {
			const raw = Array.isArray(args) ? args.join(" ") : String(args ?? "");
			const manualTitle = raw.trim();

			if (manualTitle) {
				const validated = validateTitleResponse(manualTitle);
				if (!validated) {
					cmdCtx.ui.notify("Title needs at least 2 words.", "error");
					return;
				}
				applyTitle(validated);
				cmdCtx.ui.notify(`Title: ${displayTitle()}`, "info");
				return;
			}

			const branch = cmdCtx.sessionManager.getBranch();
			const conversation = buildUserContext(branch);
			if (!conversation.trim()) {
				cmdCtx.ui.notify("No conversation to extract title from", "warning");
				return;
			}

			cmdCtx.ui.notify("Extracting title...", "info");
			const onError = (msg: string) => cmdCtx.ui.notify(`Title error: ${msg}`, "error");
			const extracted = await extractTitle(conversation, cmdCtx, cmdCtx.signal, onError, completeTitle);
			if (extracted) {
				applyTitle(extracted);
				cmdCtx.ui.notify(`Title: ${displayTitle()}`, "info");
			} else {
				clearTitle();
			}
		},
	});

	pi.on("session_start", async (_event, sessionCtx) => {
		ctx = sessionCtx;
		title = null;
		sessionTag = shortSessionId(sessionCtx.sessionManager.getSessionId());

		const storedTitle = getCurrentSessionStateIfInitialized()?.title ?? null;
		title = storedTitle?.trim() ? storedTitle : null;
		if (storedTitle !== title) persistState();

		if (title) {
			const display = displayTitle()!;
			if (sessionCtx.hasUI) sessionCtx.ui.setTitle(display);
		}

		updateWidget();
		turnCounter = 0;
	});

	pi.on("turn_end", async (_event, agentCtx) => {
		turnCounter += 1;
		if (!agentCtx.hasUI) return;

		const shouldRun = !title || turnCounter % 5 === 0;
		if (!shouldRun) return;

		const isFirst = !title;
		const conversation = buildUserContext(agentCtx.sessionManager.getBranch());
		if (!conversation.trim()) {
			pendingTitle?.abort();
			pendingTitle = null;
			return;
		}

		pendingTitle?.abort();
		const controller = new AbortController();
		pendingTitle = controller;

		void extractTitle(conversation, agentCtx, controller.signal, undefined, completeTitle)
			.then((extracted) => {
				if (controller.signal.aborted) return;
				if (extracted) applyTitle(extracted);
				else if (isFirst) clearTitle();
			})
			.catch(() => {
				if (!controller.signal.aborted && isFirst) clearTitle();
			})
			.finally(() => {
				if (pendingTitle === controller) pendingTitle = null;
			});
	});

	pi.on("session_shutdown", async () => {
		pendingTitle?.abort();
		pendingTitle = null;
		ctx = null;
	});
}
