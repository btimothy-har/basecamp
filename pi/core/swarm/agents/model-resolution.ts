import type { ModelStrategy } from "./types.ts";

interface ParentModel {
	id: string;
	provider: string;
}

export interface ResolvedModel {
	model: string | undefined;
	/** The alias name when a slashless alias failed to resolve and the parent model was used instead. */
	aliasFallback: string | null;
}

function inheritedModel(parentModel: ParentModel | undefined): string | undefined {
	if (!parentModel) return undefined;
	// Provider-qualify to avoid ambiguous resolution across providers
	return `${parentModel.provider}/${parentModel.id}`;
}

export function resolveModel(
	strategy: ModelStrategy,
	parentModel: ParentModel | undefined,
	deps: { resolveModelAlias: (alias: string) => string | undefined },
): ResolvedModel {
	switch (strategy) {
		case "default":
			return { model: undefined, aliasFallback: null };
		case "inherit":
			return { model: inheritedModel(parentModel), aliasFallback: null };
		default: {
			const aliased = deps.resolveModelAlias(strategy);
			if (aliased) return { model: aliased, aliasFallback: null };
			// Provider-qualified ids pass through untouched. A bare unresolvable alias
			// degrades to the parent model instead of sending a nonsense id to the child
			// launch (an unconfigured alias would otherwise fail every dispatch of that
			// persona); the fallback is reported so the dispatch result can surface it.
			if (strategy.includes("/")) return { model: strategy, aliasFallback: null };
			return { model: inheritedModel(parentModel), aliasFallback: strategy };
		}
	}
}
