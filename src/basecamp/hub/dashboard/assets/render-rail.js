import { append, el, replace } from "/assets/dom.js";
import { agentFiltersActive, matchingContexts, relativeTime, rootLoaderMode } from "/assets/model.js";
import { kindBadge, railSkeleton } from "/assets/render-ui.js";

export function renderRail(state, roots, sessionRail) {
	if (!state.snapshot && state.connection === "loading") {
		replace(sessionRail, railSkeleton());
		return;
	}
	if (!state.snapshot || roots.length === 0) {
		const text = !state.snapshot
			? "The hub is unavailable. Retry from the detail pane."
			: state.snapshot.roots.length
				? "No sessions match these filters."
				: "No recent sessions yet.";
		replace(sessionRail, el("div", { className: "rail-empty", text }), rootLoader(state));
		return;
	}

	const grouped = new Map();
	for (const root of roots) {
		const repos = grouped.get(root.repo) ?? new Map();
		const sessions = repos.get(root.worktree_label) ?? [];
		sessions.push(root);
		repos.set(root.worktree_label, sessions);
		grouped.set(root.repo, repos);
	}

	const groups = [];
	for (const [repo, worktrees] of grouped) {
		const repoSection = el("section", { className: "repo-group" }, el("h3", { className: "repo-heading", text: repo }));
		for (const [worktree, sessions] of worktrees) {
			append(
				repoSection,
				el(
					"div",
					{ className: "worktree-group" },
					el("h4", { className: "worktree-heading", text: worktree }),
					sessions.map((root) => sessionButton(root, state)),
				),
			);
		}
		groups.push(repoSection);
	}
	replace(sessionRail, groups, rootLoader(state));
}

function rootLoader(state) {
	const mode = rootLoaderMode(state.snapshot, state.recentRootLimit, state.loadingMoreRoots, state.connection);
	if (mode === "hidden") return null;
	if (mode === "more") return loaderButton("Load 5 more sessions", false);
	if (mode === "complete") return loaderNote("All recent sessions shown");
	if (mode === "limit") return loaderNote(`Newest ${state.snapshot.recent_root_limit_max} recent sessions shown`);
	const label =
		mode === "busy"
			? "Refresh busy · retrying…"
			: mode === "offline"
				? "Waiting for hub to load more…"
				: "Loading more sessions…";
	return loaderButton(label, true);
}

function loaderNote(text) {
	return el("div", {
		className: "root-limit-note",
		text,
		attrs: { tabindex: "-1" },
		data: { action: "loadMoreRoots" },
	});
}

function loaderButton(label, disabled) {
	return el(
		"div",
		{ className: "root-loader" },
		el("button", {
			className: "load-more-button",
			text: label,
			attrs: { type: "button", "aria-disabled": disabled, "aria-busy": disabled },
			data: { action: "loadMoreRoots" },
		}),
	);
}

function sessionButton(root, state) {
	const matching = matchingContexts(root, state.filters).map(({ agent }) => agent);
	const count = agentFiltersActive(state.filters) ? matching.length : root.agent_count;
	const countText =
		count === 0 ? "no child agents" : `${count}${root.agents_truncated ? "+" : ""} ${count === 1 ? "agent" : "agents"}`;
	const button = el(
		"button",
		{
			className: `session-button${root.root_handle === state.selectedRootHandle ? " selected" : ""}`,
			attrs: { type: "button", "aria-pressed": root.root_handle === state.selectedRootHandle },
			data: { action: "selectRoot", rootHandle: root.root_handle },
		},
		el("span", { className: `session-state-dot ${root.live ? "live" : "recent"}`, attrs: { "aria-hidden": "true" } }),
		el("span", { className: "session-title", text: root.session_name }),
		el("time", {
			className: "session-age",
			text: relativeTime(root.last_seen_at),
			attrs: { datetime: root.last_seen_at },
		}),
		el(
			"span",
			{ className: "session-meta" },
			kindBadge(root.kind),
			el("span", { className: "session-meta-text", text: `${root.agent_mode} · ${root.model} · ${countText}` }),
		),
		renderSignal(matching.length ? matching : root.agents),
	);
	return button;
}

function renderSignal(agents) {
	if (!agents.length) return el("span", { className: "signal-empty", text: "top-level session · no child agents" });
	return el(
		"span",
		{ className: "agent-signal", attrs: { "aria-hidden": "true" } },
		agents.slice(0, 7).map((agent) =>
			el("span", {
				className: `signal-segment ${agent.status}`,
				attrs: { title: `${agent.agent_type}: ${agent.status}` },
			}),
		),
	);
}
