import type { PiSwarmDependencies } from "../dependencies.ts";
import type { ModelStrategy } from "./types.ts";

interface ParentModel {
	id: string;
	provider: string;
}

export function resolveModel(
	strategy: ModelStrategy,
	parentModel: ParentModel | undefined,
	deps: Pick<PiSwarmDependencies, "resolveModelAlias">,
): string | undefined {
	switch (strategy) {
		case "default":
			return undefined;
		case "inherit":
			if (!parentModel) return undefined;
			// Provider-qualify to avoid ambiguous resolution across providers
			return `${parentModel.provider}/${parentModel.id}`;
		default:
			return deps.resolveModelAlias(strategy) ?? strategy;
	}
}
