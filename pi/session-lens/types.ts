import type { Context } from "@earendil-works/pi-ai";

export const EXPLAINER_ALIAS = "explainer";
export const SESSION_LENS_WIDGET_ID = "basecamp-session-lens";

export const LENS_OPERATIONS = ["explain", "tldr", "rephrase"] as const;
export type LensOperation = (typeof LENS_OPERATIONS)[number];

export interface LensViewport {
	columns: number;
	rows: number;
}

export interface LensBudget {
	maxCardLines: number;
	maxContentLines: number;
	maxWords: number;
	maxOutputTokens: number;
}

export interface LensRequest {
	context: Context;
	budget: LensBudget;
	estimatedInputTokens: number;
}

export interface LensResult {
	text: string;
	model: string;
	budget: LensBudget;
}

export type LensErrorCode = "aborted" | "configuration" | "context-window" | "empty" | "provider";

export class LensError extends Error {
	readonly code: LensErrorCode;

	constructor(code: LensErrorCode, message: string) {
		super(message);
		this.name = "LensError";
		this.code = code;
	}
}
