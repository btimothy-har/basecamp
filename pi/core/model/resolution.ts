import type { Api, Model, ModelThinkingLevel } from "@earendil-works/pi-ai";
import { getSupportedThinkingLevels } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { resolveModelAlias } from "./index.ts";

export function resolveModelFromString(ctx: ExtensionContext, modelName?: string): Model<Api> | undefined {
	if (!modelName) return ctx.model;

	const separator = modelName.indexOf("/");
	if (separator > 0 && separator < modelName.length - 1) {
		const provider = modelName.slice(0, separator);
		const modelId = modelName.slice(separator + 1);
		const model = ctx.modelRegistry.find(provider, modelId);
		if (model) return model;
	}

	const matches = ctx.modelRegistry.getAll().filter((model) => model.id === modelName);
	if (matches.length === 1) return matches[0];

	return ctx.model;
}

export function resolveModelReference(ctx: ExtensionContext, modelReference: string): Model<Api> | undefined {
	const separator = modelReference.indexOf("/");
	if (separator > 0 && separator < modelReference.length - 1) {
		const provider = modelReference.slice(0, separator);
		const modelId = modelReference.slice(separator + 1);
		return ctx.modelRegistry.find(provider, modelId);
	}

	const matches = ctx.modelRegistry.getAll().filter((model) => model.id === modelReference);
	return matches.length === 1 ? matches[0] : undefined;
}

export async function resolveAliasedModel(
	ctx: ExtensionContext,
	alias: string,
): Promise<{ model: Model<Api>; auth: { apiKey?: string; headers?: Record<string, string> } } | null> {
	const reference = resolveModelAlias(alias);
	if (!reference) return null;

	const model = resolveModelReference(ctx, reference);
	if (!model) return null;

	try {
		const auth = await ctx.modelRegistry.getApiKeyAndHeaders(model);
		if (!auth.ok || (!auth.apiKey && !(auth.headers && Object.keys(auth.headers).length > 0))) return null;
		return { model, auth: { apiKey: auth.apiKey, headers: auth.headers } };
	} catch {
		return null;
	}
}

const PORTABLE_THINKING_LEVELS: ModelThinkingLevel[] = ["low", "medium", "high", "xhigh"];

export function resolvePortableReasoningEffort(model: Model<Api>): ModelThinkingLevel | undefined {
	if (!model.reasoning) return undefined;

	const supported = new Set(getSupportedThinkingLevels(model));
	if (supported.has("minimal") && typeof model.thinkingLevelMap?.minimal === "string") return "minimal";
	return PORTABLE_THINKING_LEVELS.find((level) => supported.has(level));
}

export function resolveForcedToolChoice(model: Model<Api>, toolName: string): unknown {
	if (model.api === "anthropic-messages") return { type: "tool", name: toolName };
	return { type: "function", function: { name: toolName } };
}
