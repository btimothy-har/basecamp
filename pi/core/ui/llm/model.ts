import type { Api, Model } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { resolveModelAlias } from "../../platform/model-aliases.ts";
import { resolveModelFromString } from "../../platform/model-resolution.ts";

export function resolveTitleModel(): string | undefined {
	return resolveModelAlias("title");
}

export function resolveTitleModelForContext(
	ctx: ExtensionContext,
	modelName = resolveTitleModel(),
): Model<Api> | undefined {
	return resolveModelFromString(ctx, modelName);
}
