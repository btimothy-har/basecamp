import type { Api, Model } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { resolveModelAlias } from "../../model/index.ts";
import { resolveModelFromString } from "../../model/resolution.ts";

export function resolveTitleModel(): string | undefined {
	return resolveModelAlias("title");
}

export function resolveTitleModelForContext(
	ctx: ExtensionContext,
	modelName = resolveTitleModel(),
): Model<Api> | undefined {
	return resolveModelFromString(ctx, modelName);
}
