import type { Api, Model } from "@earendil-works/pi-ai";
import type { CompactionResult, ExtensionContext, SessionBeforeCompactEvent } from "@earendil-works/pi-coding-agent";
import { resolveModelAlias } from "../../model/index.ts";
import { resolveModelFromString } from "../../model/resolution.ts";

export type CompactFunction = (
	preparation: SessionBeforeCompactEvent["preparation"],
	model: Model<Api>,
	apiKey: string,
	headers?: Record<string, string>,
	customInstructions?: string,
	signal?: AbortSignal,
) => Promise<CompactionResult>;

const COMPACTION_MODEL_ALIAS = "compaction";

function isSameModel(left: Model<Api>, right: Model<Api> | undefined): boolean {
	return !!right && left.provider === right.provider && left.id === right.id;
}

export function resolveCompactionModel(ctx: ExtensionContext): Model<Api> | undefined {
	const alias = resolveModelAlias(COMPACTION_MODEL_ALIAS);
	if (!alias) return undefined;

	const model = resolveModelFromString(ctx, alias);
	if (!model || isSameModel(model, ctx.model)) return undefined;

	return model;
}

export async function generateCompactionWithModel(
	event: Pick<SessionBeforeCompactEvent, "preparation" | "customInstructions" | "signal">,
	ctx: ExtensionContext,
	compact: CompactFunction,
): Promise<{ compaction: CompactionResult } | undefined> {
	const model = resolveCompactionModel(ctx);
	if (!model) return undefined;

	let auth: { ok: true; apiKey?: string; headers?: Record<string, string> } | { ok: false; error: string };
	try {
		auth = await ctx.modelRegistry.getApiKeyAndHeaders(model);
	} catch {
		return undefined;
	}

	if (!auth.ok || !auth.apiKey) return undefined;

	try {
		const compaction = await compact(
			event.preparation,
			model,
			auth.apiKey,
			auth.headers,
			event.customInstructions,
			event.signal,
		);
		return { compaction };
	} catch {
		return undefined;
	}
}
