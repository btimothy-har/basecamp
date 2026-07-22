import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { type AgentMode, getAgentMode, onAgentModeChange } from "../agent-mode/index.ts";
import { getWorkspaceState, onWorkspaceChange, type WorkspaceState } from "../project/workspace/state.ts";
import type { DaemonConnection } from "./connection.ts";
import { deriveDaemonIdentity, sanitizeDisplayLabel } from "./identity.ts";
import type { SessionMetadataFrame } from "./protocol/index.ts";

const DISPLAY_LABEL_LIMIT = 160;

type MetadataFrame = Omit<SessionMetadataFrame, "v">;

export interface SessionMetadataPublisher {
	updateSessionName: (name: string | undefined) => void;
	updateModel: (modelId: string | null) => void;
	stop: () => void;
}

export interface SessionMetadataDeps {
	getAgentMode: () => AgentMode;
	getWorkspaceState: () => WorkspaceState | null;
	onAgentModeChange: (listener: (mode: AgentMode) => void) => () => void;
	onWorkspaceChange: (listener: (state: WorkspaceState | null) => void) => (() => void) | null;
	fallbackSessionName: (ctx: ExtensionContext) => string;
}

const DEFAULT_DEPS: SessionMetadataDeps = {
	getAgentMode,
	getWorkspaceState,
	onAgentModeChange,
	onWorkspaceChange,
	fallbackSessionName: (ctx) => deriveDaemonIdentity(ctx).session_name,
};

function optionalLabel(value: string | null | undefined): string | null {
	return sanitizeDisplayLabel(value, DISPLAY_LABEL_LIMIT);
}

function envLabel(name: string): string | null {
	return optionalLabel(process.env[name]);
}

function resolveSessionName(name: string | undefined, ctx: ExtensionContext, deps: SessionMetadataDeps): string {
	return optionalLabel(name) ?? deps.fallbackSessionName(ctx);
}

function buildFrame(sessionName: string, model: string | null, deps: SessionMetadataDeps): MetadataFrame {
	const workspace = deps.getWorkspaceState();
	return {
		type: "session_metadata",
		session_name: sessionName,
		model,
		agent_mode: deps.getAgentMode(),
		repo: optionalLabel(workspace?.repo?.name) ?? envLabel("BASECAMP_REPO"),
		worktree_label:
			workspace === null ? envLabel("BASECAMP_WORKTREE_LABEL") : optionalLabel(workspace.activeWorktree?.label),
		branch: optionalLabel(workspace?.activeWorktree?.branch),
	};
}

export function startSessionMetadataPublisher(
	pi: ExtensionAPI,
	connection: DaemonConnection,
	ctx: ExtensionContext,
	deps: SessionMetadataDeps = DEFAULT_DEPS,
): SessionMetadataPublisher {
	let sessionName = resolveSessionName(pi.getSessionName(), ctx, deps);
	let model = optionalLabel(ctx.model?.id);
	let lastPayload = "";

	const publish = (): void => {
		const frame = buildFrame(sessionName, model, deps);
		const payload = JSON.stringify(frame);
		// Reloaded Pi event handlers can converge here; identical snapshots stay wire-silent.
		if (payload === lastPayload) return;
		lastPayload = payload;
		try {
			connection.send(frame);
		} catch {
			// Connection lifecycle cleanup owns recovery; source listeners are best effort during close races.
		}
	};

	const unsubscribeMode = deps.onAgentModeChange(publish);
	const unsubscribeWorkspace = deps.onWorkspaceChange(publish);
	publish();

	return {
		updateSessionName(name) {
			sessionName = resolveSessionName(name, ctx, deps);
			publish();
		},
		updateModel(modelId) {
			model = optionalLabel(modelId);
			publish();
		},
		stop() {
			unsubscribeMode();
			unsubscribeWorkspace?.();
		},
	};
}
