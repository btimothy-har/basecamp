import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { lensCardComponent, viewportFromTerminal } from "./card.ts";
import { calculateLensBudget } from "./prompt.ts";
import type { LensOperation, LensResult, LensViewport } from "./types.ts";
import { SESSION_LENS_WIDGET_ID } from "./types.ts";

interface ActiveLens {
	token: number;
	controller: AbortController;
}

export interface LensRun {
	token: number;
	signal: AbortSignal;
}

export class LensRuntime {
	private generation = 0;
	private active: ActiveLens | null = null;

	begin(ctx: ExtensionContext): LensRun {
		if (this.active) this.dismiss(ctx);
		const controller = new AbortController();
		const token = ++this.generation;
		this.active = { token, controller };
		return { token, signal: controller.signal };
	}

	hasActive(): boolean {
		return this.active !== null;
	}

	isCurrent(token: number): boolean {
		return this.active?.token === token;
	}

	showLoading(ctx: ExtensionContext, token: number, operation: LensOperation): LensViewport {
		let viewport: LensViewport = { columns: 80, rows: 24 };
		if (!this.isCurrent(token)) return viewport;

		ctx.ui.setWidget(
			SESSION_LENS_WIDGET_ID,
			(tui, theme) => {
				viewport = viewportFromTerminal(tui.terminal);
				return lensCardComponent(
					{
						operation,
						body: "Preparing the visible session context…",
						budget: calculateLensBudget(operation, viewport),
						loading: true,
					},
					theme,
					tui.terminal,
				);
			},
			{ placement: "aboveEditor" },
		);
		return viewport;
	}

	showResult(ctx: ExtensionContext, token: number, operation: LensOperation, result: LensResult): boolean {
		if (!this.isCurrent(token)) return false;
		ctx.ui.setWidget(
			SESSION_LENS_WIDGET_ID,
			(tui, theme) =>
				lensCardComponent(
					{
						operation,
						body: result.text,
						budget: result.budget,
						model: result.model,
						truncated: result.truncated,
					},
					theme,
					tui.terminal,
				),
			{ placement: "aboveEditor" },
		);
		return true;
	}

	dismiss(ctx: ExtensionContext): void {
		this.generation++;
		this.active?.controller.abort();
		this.active = null;
		ctx.ui.setWidget(SESSION_LENS_WIDGET_ID, undefined, { placement: "aboveEditor" });
	}
}
