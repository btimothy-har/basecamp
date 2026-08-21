import type { Api, AssistantMessage, Model } from "@earendil-works/pi-ai";
import { uuidv7 } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { resolveModelAlias } from "#core/model/index.ts";
import { resolveModelReference } from "#core/model/resolution.ts";
import { requestTokenLimit } from "./prompt.ts";
import { EXPLAINER_ALIAS, LensError, type LensRequest, type LensResult } from "./types.ts";

export interface LensCompletionDeps {
	resolveAlias(alias: string): string | undefined;
	resolveModel(ctx: ExtensionContext, reference: string): Model<Api> | undefined;
	createSessionId(): string;
}

const DEFAULT_DEPS: LensCompletionDeps = {
	resolveAlias: resolveModelAlias,
	resolveModel: resolveModelReference,
	createSessionId: uuidv7,
};

function responseText(content: Array<{ type: string; text?: string }>): string {
	return content
		.filter((part): part is { type: "text"; text: string } => part.type === "text" && typeof part.text === "string")
		.map((part) => part.text)
		.join("\n")
		.trim();
}

function explainerModel(ctx: ExtensionContext, deps: LensCompletionDeps): Model<Api> {
	const reference = deps.resolveAlias(EXPLAINER_ALIAS);
	const model = reference ? deps.resolveModel(ctx, reference) : undefined;
	if (!model) {
		throw new LensError(
			"configuration",
			"Configure a valid `explainer` model alias with /model-aliases before using session lenses.",
		);
	}
	return model;
}

export async function completeLens(
	ctx: ExtensionContext,
	request: LensRequest,
	signal: AbortSignal,
	deps: LensCompletionDeps = DEFAULT_DEPS,
): Promise<LensResult> {
	const model = explainerModel(ctx, deps);
	const maxTokens = requestTokenLimit(request, model);
	if (maxTokens === null) {
		throw new LensError(
			"context-window",
			`The explainer model's ${model.contextWindow.toLocaleString()}-token context window is too small for this session.`,
		);
	}
	if (signal.aborted) throw new LensError("aborted", "Session lens cancelled.");

	const auth = await ctx.modelRegistry.getApiKeyAndHeaders(model);
	if (!auth.ok) {
		throw new LensError("configuration", `The explainer model is unavailable: ${auth.error}`);
	}
	if (signal.aborted) throw new LensError("aborted", "Session lens cancelled.");

	let response: AssistantMessage;
	try {
		response = await ctx.modelRegistry.complete(model, request.context, {
			cacheRetention: "none",
			maxTokens,
			sessionId: deps.createSessionId(),
			signal,
		});
	} catch (error) {
		if (signal.aborted) throw new LensError("aborted", "Session lens cancelled.");
		throw new LensError("provider", error instanceof Error ? error.message : String(error));
	}

	if (signal.aborted || response.stopReason === "aborted") {
		throw new LensError("aborted", "Session lens cancelled.");
	}
	if (response.stopReason === "error") {
		throw new LensError("provider", response.errorMessage ?? "The explainer model returned an error.");
	}

	const text = responseText(response.content);
	if (!text) throw new LensError("empty", "The explainer model returned no text.");
	return { text, model: `${model.provider}/${model.id}`, budget: request.budget };
}
