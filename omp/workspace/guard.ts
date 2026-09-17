/**
 * Structured-mutation guard for the canonical checkout. Blocks known
 * path-declaring mutation tools (write/edit/ast_edit/LSP refactors) whose
 * resolved targets land in the launch protected root or the live repository's
 * canonical (primary) checkout. Bash, eval, task, process, raw LSP requests,
 * custom/MCP tools, and every non-canonical path stay permitted — this is an
 * accidental-write boundary, not a sandbox.
 */
import type { ExtensionAPI, ExtensionContext, ToolCallEvent, ToolCallEventResult } from "@oh-my-pi/pi-coding-agent";
import { expandDelimitedPathEntries } from "@oh-my-pi/pi-coding-agent/tools/path-utils";
import { type EditInspection, editInspect } from "@oh-my-pi/pi-natives";
import type { WorkspaceEnvironment } from "./environment.ts";
import {
	collectWriteTargets,
	normalizeRoot,
	resolveFilesystemTarget,
	resolveScopePrefix,
	sameOrWithin,
} from "./paths.ts";
import type { RepositoryCache } from "./repository.ts";

export const CANONICAL_BLOCK_REASON = "Canonical checkout is read-only. Use /wt <branch> for repository edits.";

export interface WorkspaceGuardDeps {
	env: WorkspaceEnvironment;
	repos: RepositoryCache;
}

/** Include the launch root and every canonical checkout discovered this session. */
function protectedRoots(ctx: ExtensionContext, deps: WorkspaceGuardDeps): string[] {
	const roots = new Set(deps.repos.primaryRoots().map(normalizeRoot));
	if (deps.env.protectedRoot) roots.add(normalizeRoot(deps.env.protectedRoot));
	const identity = deps.repos.identify(ctx.cwd);
	if (identity) roots.add(normalizeRoot(identity.primaryRoot));
	return [...roots];
}

type GuardInput = Record<string, unknown>;

function stringField(input: GuardInput, key: string): string | undefined {
	const value = input[key];
	return typeof value === "string" && value.length > 0 ? value : undefined;
}

/** Targets of an edit call: normalized guard-only fields plus native inspection of the raw payload. */
export function collectEditTargets(input: GuardInput): string[] {
	const targets = new Set<string>();
	const path = stringField(input, "path") ?? stringField(input, "_path");
	if (path) targets.add(path);
	if (Array.isArray(input.paths)) {
		for (const entry of input.paths) if (typeof entry === "string" && entry.length > 0) targets.add(entry);
	}
	const edits = Array.isArray(input.edits) ? input.edits : [];
	for (const entry of edits) {
		if (entry && typeof entry === "object") {
			const rename = (entry as GuardInput).rename;
			if (typeof rename === "string" && rename.length > 0) targets.add(rename);
		}
	}
	const addInspection = (inspection: EditInspection): void => {
		for (const inspected of inspection.paths) targets.add(inspected);
		for (const op of inspection.fileOps) {
			targets.add(op.path);
			if (op.to) targets.add(op.to);
		}
	};
	if (path) {
		// Path-shaped payload: replace carries old/new strings, patch carries edits[].
		try {
			addInspection(editInspect(edits.length > 0 ? "patch" : "replace", JSON.stringify(input)));
		} catch {
			// Unparseable payloads fail natively; normalized fields above still guard them.
		}
	}
	for (const key of ["input", "_input"] as const) {
		const text = stringField(input, key);
		if (!text) continue;
		for (const mode of ["hashline", "apply_patch", "sloppy"] as const) {
			try {
				addInspection(editInspect(mode, JSON.stringify({ input: text })));
			} catch {
				// A payload that is not valid in this mode contributes no targets.
			}
		}
	}
	return [...targets];
}

/** Declared targets of an applying LSP refactor/action; preview-only calls pass. */
export function collectLspTargets(input: GuardInput): string[] {
	const action = stringField(input, "action")?.toLowerCase();
	if (action === "rename" || action === "rename_file") {
		if (input.apply === false) return [];
		const targets: string[] = [];
		const file = stringField(input, "file");
		if (file) targets.push(file);
		if (action === "rename_file") {
			const destination = stringField(input, "new_name");
			if (destination) targets.push(destination);
		}
		return targets;
	}
	if (action === "code_actions" && input.apply === true) {
		const file = stringField(input, "file");
		return file ? [file] : [];
	}
	return [];
}

/** Fixed scope prefixes of an ast_edit call (files, directories, glob prefixes). */
export function collectAstScopes(input: GuardInput): string[] {
	if (!Array.isArray(input.paths)) return [];
	const scopes: string[] = [];
	for (const entry of input.paths) if (typeof entry === "string" && entry.length > 0) scopes.push(entry);
	return scopes;
}

/**
 * The tool_call handler. Re-reads the live cwd and Git identity on every
 * event so `/wt`, `/move`, and resume rerooting are honored, and never returns
 * replacement input — only a block verdict.
 */
export function guardToolCall(
	event: ToolCallEvent,
	ctx: ExtensionContext,
	deps: WorkspaceGuardDeps,
): Promise<ToolCallEventResult | undefined> | ToolCallEventResult | undefined {
	const roots = protectedRoots(ctx, deps);
	if (roots.length === 0) return undefined;
	const input = event.input as GuardInput;
	const hitsCanonical = (rawPath: string): boolean => {
		const resolved = resolveFilesystemTarget(rawPath, ctx.cwd, ctx.localProtocolOptions);
		return resolved !== null && roots.some((root) => sameOrWithin(root, resolved));
	};
	let blocked = false;
	switch (event.toolName) {
		case "write": {
			const rawPath = stringField(input, "path");
			blocked = rawPath !== undefined && collectWriteTargets(rawPath).some(hitsCanonical);
			break;
		}
		case "edit":
			blocked = collectEditTargets(input).some(hitsCanonical);
			break;
		case "ast_edit":
			return expandDelimitedPathEntries(collectAstScopes(input), ctx.cwd).then((scopes) => {
				const reachesCanonical = scopes.some((scope) => {
					const resolved = resolveScopePrefix(scope, ctx.cwd);
					return (
						resolved !== null && roots.some((root) => sameOrWithin(root, resolved) || sameOrWithin(resolved, root))
					);
				});
				return reachesCanonical ? { block: true, reason: CANONICAL_BLOCK_REASON } : undefined;
			});
		case "lsp":
			blocked = collectLspTargets(input).some(hitsCanonical);
			break;
		default:
			return undefined;
	}
	return blocked ? { block: true, reason: CANONICAL_BLOCK_REASON } : undefined;
}

export default function registerWorkspaceGuard(pi: ExtensionAPI, deps: WorkspaceGuardDeps): void {
	pi.on("tool_call", (event, ctx) => guardToolCall(event, ctx, deps));
}
