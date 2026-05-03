import { resolveModelAlias } from "../../../platform/model-aliases.ts";

export function resolveTitleModel(): string | undefined {
	return resolveModelAlias("fast");
}
