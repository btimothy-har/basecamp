import type { Api, Model } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";

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
