import { resolveModelAlias } from "../../../platform/model-aliases.ts";
import type { ModelStrategy } from "./types.ts";

interface ParentModel {
	id: string;
	provider: string;
}

export function resolveModel(strategy: ModelStrategy, parentModel: ParentModel | undefined): string | undefined {
	switch (strategy) {
		case "default":
			return undefined;
		case "inherit":
			if (!parentModel) return undefined;
			// Provider-qualify to avoid ambiguous resolution across providers
			return `${parentModel.provider}/${parentModel.id}`;
		default:
			return resolveModelAlias(strategy) ?? strategy;
	}
}
