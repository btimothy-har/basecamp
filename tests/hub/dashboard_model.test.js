import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	assignment,
	canLoadMoreRoots,
	contextsForRoot,
	defaultStageIndex,
	EMPTY_FILTERS,
	elapsedTime,
	MAX_RECENT_ROOT_LIMIT,
	nextRecentRootLimit,
	normalizeSnapshot,
	parseRoute,
	progressPercent,
	relativeTime,
	rootLoaderMode,
	routeFor,
	selectedStage,
	snapshotFailureState,
	stagesForRoot,
	visibleContexts,
	visibleRoots,
} from "../../src/basecamp/hub/dashboard/assets/model.js";

function fixture() {
	return normalizeSnapshot({
		generated_at: "2026-07-21T12:00:00Z",
		window_hours: 24,
		recent_root_limit: 5,
		recent_root_limit_max: 50,
		roots_truncated: true,
		roots: [
			{
				root_handle: "root.handle",
				session_name: "Session <script>",
				repo: "acme/widgets",
				worktree_label: "wt-bt/dashboard",
				kind: "root",
				live: true,
				agent_count: 3,
				agents: [
					{
						agent_handle: "agent-a",
						parent_handle: "root.handle",
						agent_type: "scout",
						status: "running",
					},
					{
						agent_handle: "agent-b",
						parent_handle: "agent-a",
						agent_type: "scout",
						status: "running",
					},
					{
						agent_handle: "agent-c",
						parent_handle: "agent-b",
						agent_type: "testing-specialist",
						status: "completed",
					},
				],
			},
		],
	});
}

describe("dashboard model", () => {
	it("normalizes roots and reconstructs arbitrary-depth ancestry", () => {
		const snapshot = fixture();
		const root = snapshot.roots[0];
		const contexts = contextsForRoot(root);

		assert.equal(root.session_name, "Session <script>");
		assert.deepEqual(
			contexts.map(({ agent, depth, ancestors }) => [
				agent.agent_handle,
				depth,
				ancestors.map((ancestor) => ancestor.agent_handle),
			]),
			[
				["agent-a", 0, []],
				["agent-b", 1, ["agent-a"]],
				["agent-c", 2, ["agent-a", "agent-b"]],
			],
		);
	});

	it("normalizes bounded root metadata and loader states", () => {
		const snapshot = fixture();
		assert.equal(snapshot.window_hours, 24);
		assert.equal(snapshot.recent_root_limit, 5);
		assert.equal(snapshot.recent_root_limit_max, 50);
		assert.equal(snapshot.roots_truncated, true);
		assert.equal(canLoadMoreRoots(snapshot, 5), true);
		assert.equal(nextRecentRootLimit(5, snapshot.recent_root_limit_max), 10);
		assert.equal(nextRecentRootLimit(48, snapshot.recent_root_limit_max), MAX_RECENT_ROOT_LIMIT);
		assert.equal(canLoadMoreRoots(snapshot, MAX_RECENT_ROOT_LIMIT), false);
		assert.equal(rootLoaderMode(snapshot, 5, false, "connected"), "more");
		assert.equal(rootLoaderMode(snapshot, 10, true, "connected"), "loading");
		assert.equal(rootLoaderMode(snapshot, 10, false, "busy"), "busy");
		assert.equal(rootLoaderMode(snapshot, 10, false, "offline"), "offline");
		assert.equal(
			rootLoaderMode(
				{ ...snapshot, recent_root_limit: MAX_RECENT_ROOT_LIMIT },
				MAX_RECENT_ROOT_LIMIT,
				false,
				"connected",
			),
			"limit",
		);
		assert.equal(rootLoaderMode({ ...snapshot, roots_truncated: false }, 5, false, "connected"), "hidden");
		assert.equal(rootLoaderMode({ ...snapshot, roots_truncated: false }, 10, false, "connected"), "complete");
		assert.equal(snapshotFailureState(429, true), "busy");
		assert.equal(snapshotFailureState(429, false), "loading");
		assert.equal(snapshotFailureState(503, true), "offline");

		const minimum = normalizeSnapshot({ recent_root_limit: 1, recent_root_limit_max: 50, roots: [] });
		assert.equal(minimum.recent_root_limit, 1);
		assert.equal(nextRecentRootLimit(minimum.recent_root_limit, minimum.recent_root_limit_max), 6);

		const defaults = normalizeSnapshot({ roots: [] });
		assert.equal(defaults.window_hours, 24);
		assert.equal(defaults.recent_root_limit, 5);
		assert.equal(defaults.recent_root_limit_max, 50);
		assert.equal(defaults.roots_truncated, false);
	});

	it("retains ancestors as context under agent filters", () => {
		const root = fixture().roots[0];
		const filters = { ...EMPTY_FILTERS, status: "completed", type: "testing-specialist" };
		const contexts = visibleContexts(root, filters);

		assert.deepEqual(
			contexts.map(({ agent, contextOnly }) => [agent.agent_handle, contextOnly]),
			[
				["agent-a", true],
				["agent-b", true],
				["agent-c", false],
			],
		);
		assert.equal(visibleRoots(fixture(), filters).length, 1);
		assert.equal(visibleRoots(fixture(), { ...filters, status: "failed" }).length, 0);
	});

	it("applies every root facet filter independently", () => {
		const snapshot = fixture();
		assert.equal(visibleRoots(snapshot, { ...EMPTY_FILTERS, repo: "acme/widgets" }).length, 1);
		assert.equal(visibleRoots(snapshot, { ...EMPTY_FILTERS, worktree: "wt-bt/dashboard" }).length, 1);
		assert.equal(visibleRoots(snapshot, { ...EMPTY_FILTERS, kind: "root" }).length, 1);
		assert.equal(visibleRoots(snapshot, { ...EMPTY_FILTERS, liveOnly: true }).length, 1);
		assert.equal(visibleRoots(snapshot, { ...EMPTY_FILTERS, repo: "other/repo" }).length, 0);
	});

	it("builds a fallback stage and derives bounded display values", () => {
		const root = fixture().roots[0];
		root.task = {
			goal: "Ship the dashboard",
			progress: { completed: 1, deleted: 0, total: 2 },
			task_plan: [{ index: 0, label: "Build interface", status: "active" }],
			current_task: { index: 0, label: "Build interface", status: "active", description: "" },
		};
		const stages = stagesForRoot(root);
		assert.equal(stages.length, 1);
		assert.equal(defaultStageIndex(root), 0);
		assert.equal(selectedStage(root, 99).goal, "Ship the dashboard");
		assert.equal(progressPercent(stages[0].progress), 50);
		assert.equal(assignment({ task: root.task, session_name: "fallback" }), "Build interface");
	});

	it("formats relative and elapsed time at stable boundaries", () => {
		const now = Date.parse("2026-07-21T12:00:00Z");
		assert.equal(relativeTime("2026-07-21T11:59:30Z", now), "now");
		assert.equal(relativeTime("2026-07-21T11:30:00Z", now), "30m");
		assert.equal(elapsedTime("2026-07-21T11:58:35Z", "2026-07-21T12:00:00Z"), "01:25");
		assert.equal(elapsedTime("invalid", null, now), "—");
		assert.equal(progressPercent({ completed: 4, total: 0 }), 0);
	});

	it("rejects malformed snapshots and invalid public handles", () => {
		assert.throws(() => normalizeSnapshot({ roots: null }), /Invalid dashboard snapshot/);
		const snapshot = normalizeSnapshot({
			roots: [{ root_handle: "valid-root", agents: [{ agent_handle: "bad/agent" }] }, { root_handle: "bad/root" }],
		});
		assert.deepEqual(
			snapshot.roots.map((root) => root.root_handle),
			["valid-root"],
		);
		assert.equal(snapshot.roots[0].agents.length, 0);
	});

	it("round-trips public-handle hash routes and rejects malformed routes", () => {
		const hash = routeFor("root.handle", "agent-c");
		assert.equal(hash, "#/sessions/root.handle/agents/agent-c");
		assert.deepEqual(parseRoute(hash), { rootHandle: "root.handle", agentHandle: "agent-c" });
		assert.deepEqual(parseRoute("#/sessions/root.handle"), { rootHandle: "root.handle", agentHandle: null });
		assert.equal(parseRoute("#/sessions/root/agents/agent/extra"), null);
		assert.equal(parseRoute("#/sessions/root/agents/bad%2Fhandle"), null);
	});
});
