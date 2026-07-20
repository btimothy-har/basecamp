import type { Api, Model, ModelThinkingLevel } from "@earendil-works/pi-ai";
import { getSupportedThinkingLevels } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { resolveModelAlias } from "./index.ts";

/** Split a `provider/modelId` reference; null when there is no interior `/`. */
function parseProviderModelRef(reference: string): { provider: string; modelId: string } | null {
	const separator = reference.indexOf("/");
	if (separator > 0 && separator < reference.length - 1) {
		return { provider: reference.slice(0, separator), modelId: reference.slice(separator + 1) };
	}
	return null;
}

/** The single registry model whose id exactly equals `id`, or undefined if not exactly one. */
function findModelByExactId(ctx: ExtensionContext, id: string): Model<Api> | undefined {
	const matches = ctx.modelRegistry.getAll().filter((model) => model.id === id);
	return matches.length === 1 ? matches[0] : undefined;
}

export function resolveModelFromString(ctx: ExtensionContext, modelName?: string): Model<Api> | undefined {
	if (!modelName) return ctx.model;

	const ref = parseProviderModelRef(modelName);
	if (ref) {
		// Intentional divergence from resolveModelReference: a provider/modelId that fails
		// to resolve falls through to an exact-id match rather than returning the failed
		// lookup. Pinned by model/tests/resolution.test.ts.
		const model = ctx.modelRegistry.find(ref.provider, ref.modelId);
		if (model) return model;
	}

	return findModelByExactId(ctx, modelName) ?? ctx.model;
}

export function resolveModelReference(ctx: ExtensionContext, modelReference: string): Model<Api> | undefined {
	const ref = parseProviderModelRef(modelReference);
	if (ref) return ctx.modelRegistry.find(ref.provider, ref.modelId);
	return findModelByExactId(ctx, modelReference);
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
	if (model.api === "openai-responses") return { type: "function", name: toolName };
	if (model.api === "openai-codex-responses") return "required";
	return { type: "function", function: { name: toolName } };
}
