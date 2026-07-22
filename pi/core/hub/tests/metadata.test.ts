import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { AgentMode } from "../../agent-mode/index.ts";
import type { WorkspaceState } from "../../project/workspace/state.ts";
import type { DaemonConnection } from "../connection.ts";
import { type SessionMetadataDeps, type SessionMetadataPublisher, startSessionMetadataPublisher } from "../metadata.ts";
import type { OutboundFrame } from "../protocol/index.ts";
import {
	clearHubMetadataWiring,
	createHubMetadataWiring,
	getHubMetadataPublisher,
	type HubConnectionState,
	replaceHubMetadataWiring,
} from "../state.ts";

function workspace(active: boolean): WorkspaceState {
	return {
		launchCwd: "/repo",
		effectiveCwd: active ? "/worktrees/dashboard" : "/repo",
		scratchDir: "/tmp/basecamp",
		repo: { isRepo: true, name: "acme/widgets", root: "/repo", remoteUrl: null },
		protectedRoot: "/repo",
		activeWorktree: active
			? {
					kind: "git-worktree",
					label: "wt-bt/dashboard",
					path: "/worktrees/dashboard",
					branch: "bt/dashboard",
					created: false,
				}
			: null,
		unsafeEdit: false,
	};
}

describe("session metadata wiring", () => {
	it("replaces reload ownership and ignores stale close callbacks", () => {
		const state: HubConnectionState = { connection: null, connecting: null, metadataWiring: null };
		let stoppedA = 0;
		let stoppedB = 0;
		let closeUnsubscribedA = 0;
		let closeUnsubscribedB = 0;
		let namesA = 0;
		let namesB = 0;
		let modelsA = 0;
		let modelsB = 0;
		const publisherA: SessionMetadataPublisher = {
			updateSessionName: () => namesA++,
			updateModel: () => modelsA++,
			stop: () => stoppedA++,
		};
		const publisherB: SessionMetadataPublisher = {
			updateSessionName: () => namesB++,
			updateModel: () => modelsB++,
			stop: () => stoppedB++,
		};
		const wiringA = createHubMetadataWiring(publisherA, () => closeUnsubscribedA++);
		const staleClose = () => clearHubMetadataWiring(state, wiringA);
		replaceHubMetadataWiring(state, wiringA);

		const wiringB = createHubMetadataWiring(publisherB, () => closeUnsubscribedB++);
		replaceHubMetadataWiring(state, wiringB);
		assert.equal(stoppedA, 1);
		assert.equal(closeUnsubscribedA, 1);

		getHubMetadataPublisher(state)?.updateSessionName("Current session");
		getHubMetadataPublisher(state)?.updateModel("current-model");
		assert.deepEqual({ namesA, modelsA, namesB, modelsB }, { namesA: 0, modelsA: 0, namesB: 1, modelsB: 1 });

		assert.equal(staleClose(), false);
		assert.equal(state.metadataWiring, wiringB);
		assert.equal(stoppedB, 0);

		assert.equal(clearHubMetadataWiring(state, wiringB), true);
		assert.equal(clearHubMetadataWiring(state, wiringB), false);
		assert.equal(state.metadataWiring, null);
		assert.equal(stoppedB, 1);
		assert.equal(closeUnsubscribedB, 1);
	});
});

describe("session metadata publisher", () => {
	it("publishes full snapshots, exact nulls, and source changes", () => {
		const sent: OutboundFrame[] = [];
		let mode: AgentMode = "planning";
		let currentWorkspace = workspace(true);
		let modeListener = (_mode: AgentMode): void => {};
		let workspaceListener = (_state: WorkspaceState | null): void => {};
		let modeUnsubscribed = false;
		let workspaceUnsubscribed = false;
		const deps: SessionMetadataDeps = {
			getAgentMode: () => mode,
			getWorkspaceState: () => currentWorkspace,
			onAgentModeChange(listener) {
				modeListener = listener;
				return () => {
					modeUnsubscribed = true;
				};
			},
			onWorkspaceChange(listener) {
				workspaceListener = listener;
				return () => {
					workspaceUnsubscribed = true;
				};
			},
			fallbackSessionName: () => "session-fallback",
		};
		const connection = {
			send(frame: OutboundFrame) {
				sent.push(frame);
			},
		} as unknown as DaemonConnection;
		const pi = { getSessionName: () => "Initial session" } as any;
		const ctx = { model: { id: "claude-sonnet-4-5" } } as any;

		const publisher = startSessionMetadataPublisher(pi, connection, ctx, deps);
		assert.deepEqual(sent[0], {
			type: "session_metadata",
			session_name: "Initial session",
			model: "claude-sonnet-4-5",
			agent_mode: "planning",
			repo: "acme/widgets",
			worktree_label: "wt-bt/dashboard",
			branch: "bt/dashboard",
		});

		publisher.updateSessionName(undefined);
		publisher.updateModel(null);
		mode = "copilot";
		modeListener(mode);
		currentWorkspace = workspace(false);
		workspaceListener(currentWorkspace);
		assert.deepEqual(sent.at(-1), {
			type: "session_metadata",
			session_name: "session-fallback",
			model: null,
			agent_mode: "copilot",
			repo: "acme/widgets",
			worktree_label: null,
			branch: null,
		});

		const count = sent.length;
		publisher.updateModel(null);
		assert.equal(sent.length, count);
		publisher.stop();
		assert.equal(modeUnsubscribed, true);
		assert.equal(workspaceUnsubscribed, true);
	});

	it("uses environment facets before workspace initialization", () => {
		const priorRepo = process.env.BASECAMP_REPO;
		const priorWorktree = process.env.BASECAMP_WORKTREE_LABEL;
		process.env.BASECAMP_REPO = "acme/widgets";
		process.env.BASECAMP_WORKTREE_LABEL = "copilot/gentle-otter-quill";
		const sent: OutboundFrame[] = [];
		const deps: SessionMetadataDeps = {
			getAgentMode: () => "work",
			getWorkspaceState: () => null,
			onAgentModeChange: () => () => {},
			onWorkspaceChange: () => null,
			fallbackSessionName: () => "session-fallback",
		};
		const connection = {
			send(frame: OutboundFrame) {
				sent.push(frame);
			},
		} as unknown as DaemonConnection;

		try {
			const publisher = startSessionMetadataPublisher(
				{ getSessionName: () => undefined } as any,
				connection,
				{ model: null } as any,
				deps,
			);
			assert.deepEqual(sent[0], {
				type: "session_metadata",
				session_name: "session-fallback",
				model: null,
				agent_mode: "work",
				repo: "acme/widgets",
				worktree_label: "copilot/gentle-otter-quill",
				branch: null,
			});
			publisher.stop();
		} finally {
			if (priorRepo === undefined) delete process.env.BASECAMP_REPO;
			else process.env.BASECAMP_REPO = priorRepo;
			if (priorWorktree === undefined) delete process.env.BASECAMP_WORKTREE_LABEL;
			else process.env.BASECAMP_WORKTREE_LABEL = priorWorktree;
		}
	});
});
