import { afterEach, describe, expect, setDefaultTimeout, test } from "bun:test";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type as arktype } from "@oh-my-pi/omptype";
import type {
	ExtensionAPI,
	ExtensionCommandContext,
	ExtensionContext,
	RegisteredCommand,
	ToolDefinition,
} from "@oh-my-pi/pi-coding-agent";
import registerReview from "../index.ts";

const REVIEW_MODES = ["Against a base branch", "Specific commit", "Custom instructions"];
const tempRoots: string[] = [];
setDefaultTimeout(20_000);

function git(cwd: string, ...args: string[]): string {
	return execFileSync("git", args, {
		cwd,
		encoding: "utf8",
		env: { ...process.env, GIT_CONFIG_NOSYSTEM: "1" },
	});
}

function commit(cwd: string, message: string): string {
	git(cwd, "add", "-A");
	git(cwd, "-c", "commit.gpgSign=false", "commit", "-m", message);
	return git(cwd, "rev-parse", "HEAD").trim();
}

interface GitFixture {
	parent: string;
	root: string;
	feature: string;
	featureTwo: string;
	unrelated: string;
	baseRevision: string;
	mergeRevision: string;
}

function createGitFixture(): GitFixture {
	const parent = mkdtempSync(join(tmpdir(), "omp-review-"));
	tempRoots.push(parent);
	const root = join(parent, "repo with ' $(touch ESCAPED)");
	mkdirSync(root);
	git(root, "init", "-b", "main");
	git(root, "config", "user.name", "Basecamp Test");
	git(root, "config", "user.email", "basecamp@example.test");
	git(root, "config", "commit.gpgsign", "false");
	writeFileSync(join(root, "shared.txt"), "BASE\n");
	const baseRevision = commit(root, "base");
	git(root, "branch", "feature", baseRevision);
	writeFileSync(join(root, "main-only.txt"), "MAIN_ONLY\n");
	commit(root, "main only");

	const feature = join(parent, "feature worktree");
	git(root, "worktree", "add", feature, "feature");
	writeFileSync(join(feature, "feature.txt"), "FEATURE_ONLY\n");
	commit(feature, "feature");

	const side = join(parent, "side worktree");
	git(root, "worktree", "add", "-b", "side", side, baseRevision);
	writeFileSync(join(side, "side.txt"), "SIDE_ONLY\n");
	commit(side, "side");
	git(feature, "merge", "--no-ff", "side", "-m", "merge side");
	const mergeRevision = git(feature, "rev-parse", "HEAD").trim();

	const featureTwo = join(parent, "second feature");
	git(root, "worktree", "add", "-b", "feature-two", featureTwo, baseRevision);
	writeFileSync(join(featureTwo, "second.txt"), "SECOND_ONLY\n");
	commit(featureTwo, "second feature");

	const unrelated = join(parent, "unrelated worktree");
	git(root, "worktree", "add", "--detach", unrelated, baseRevision);
	git(unrelated, "switch", "--orphan", "unrelated");
	rmSync(join(unrelated, "shared.txt"), { force: true });
	writeFileSync(join(unrelated, "unrelated.txt"), "UNRELATED\n");
	commit(unrelated, "unrelated root");

	writeFileSync(join(feature, "staged.txt"), "DIRTY_STAGED\n");
	git(feature, "add", "staged.txt");
	writeFileSync(join(feature, "feature.txt"), "FEATURE_ONLY\nDIRTY_UNSTAGED\n");
	writeFileSync(join(feature, "untracked.txt"), "DIRTY_UNTRACKED\n");
	return { parent, root, feature, featureTwo, unrelated, baseRevision, mergeRevision };
}

interface InvokeOptions {
	selections?: Array<string | undefined>;
	editors?: Array<string | undefined>;
	hasUI?: boolean;
	idle?: boolean;
	changeOriginAfterFirstSelection?: boolean;
}

function createHarness() {
	const sent: string[] = [];
	const notifications: Array<{ message: string; level: string | undefined }> = [];
	const menus: Array<{ title: string; options: string[] }> = [];
	const commands: Record<string, RegisteredCommand> = {};
	const hooks: Partial<Record<string, Array<(event: unknown, ctx: ExtensionContext) => unknown>>> = {};
	const api = {
		arktype,
		on(event: string, handler: (event: unknown, ctx: ExtensionContext) => unknown): void {
			const handlers = hooks[event] ?? [];
			handlers.push(handler);
			hooks[event] = handlers;
		},
		registerCommand(name: string, command: Omit<RegisteredCommand, "name">): void {
			commands[name] = { name, ...command };
		},
		registerTool(_tool: ToolDefinition): void {},
		sendUserMessage(content: string | unknown[]): void {
			if (typeof content !== "string") throw new Error("review command sent non-text content");
			sent.push(content);
		},
	} as unknown as ExtensionAPI;
	registerReview(api);
	const command = commands.review;
	if (!command) throw new Error("review command was not registered");

	return {
		sent,
		notifications,
		menus,
		hooks,
		invoke: async (cwd: string, args = "", options: InvokeOptions = {}) => {
			let liveCwd = cwd;
			let liveSessionId = "session-1";
			let selectIndex = 0;
			let editorIndex = 0;
			const ctx = {
				cwd,
				hasUI: options.hasUI ?? true,
				isIdle: () => options.idle ?? true,
				ui: {
					select: async (title: string, items: Array<string | { label: string }>) => {
						menus.push({ title, options: items.map((item) => (typeof item === "string" ? item : item.label)) });
						const answer = options.selections?.[selectIndex++];
						if (options.changeOriginAfterFirstSelection && selectIndex === 1) {
							liveCwd = `${cwd}-moved`;
							liveSessionId = "session-2";
						}
						return answer;
					},
					editor: async () => options.editors?.[editorIndex++],
					notify: (message: string, level?: string) => notifications.push({ message, level }),
				},
				sessionManager: {
					getCwd: () => liveCwd,
					getSessionId: () => liveSessionId,
				},
			} as unknown as ExtensionCommandContext;
			const sentBefore = sent.length;
			await command.handler(args, ctx);
			return sent.length > sentBefore ? sent.at(-1) : undefined;
		},
	};
}

function promptValue(request: string, label: string): string {
	const prefix = `- ${label}: `;
	const line = request.split("\n").find((candidate) => candidate.startsWith(prefix));
	if (!line) throw new Error(`request has no ${label} value:\n${request}`);
	return line.slice(prefix.length);
}

function runBranchReview(cwd: string, request: string): string {
	return git(
		cwd,
		"diff",
		promptValue(request, "Comparison base (merge base)"),
		promptValue(request, "Head revision"),
		"--",
	);
}

function runCommitReview(cwd: string, request: string): string {
	return git(cwd, "show", "--format=fuller", "--patch", promptValue(request, "Commit"), "--");
}

afterEach(() => {
	for (const root of tempRoots.splice(0)) rmSync(root, { recursive: true, force: true });
});

describe("Basecamp /review", () => {
	test("uses each invocation's linked worktree and a committed merge-base scope", async () => {
		const fixture = createGitFixture();
		const h = createHarness();
		await h.invoke(fixture.feature, "focus on behavior", {
			selections: ["Against a base branch", "main"],
		});

		expect(h.menus[0]?.title).toContain(fixture.feature);
		expect(h.menus[0]?.options).toEqual(REVIEW_MODES);
		expect(h.menus[1]?.options).not.toContain("feature");
		const featureOutput = runBranchReview(fixture.feature, h.sent[0]!);
		expect(featureOutput).toContain("FEATURE_ONLY");
		expect(featureOutput).toContain("SIDE_ONLY");
		expect(featureOutput).not.toContain("MAIN_ONLY");
		expect(featureOutput).not.toContain("DIRTY_STAGED");
		expect(featureOutput).not.toContain("DIRTY_UNSTAGED");
		expect(featureOutput).not.toContain("DIRTY_UNTRACKED");
		expect(h.sent[0]).toContain("focus on behavior");
		expect(h.sent[0]).toContain("skill://code-review");
		expect(h.sent[0]).toContain(`- Repository: ${JSON.stringify(fixture.feature)}`);

		await h.invoke(fixture.featureTwo, "", { selections: ["Against a base branch", "main"] });
		const secondOutput = runBranchReview(fixture.featureTwo, h.sent[1]!);
		expect(secondOutput).toContain("SECOND_ONLY");
		expect(secondOutput).not.toContain("FEATURE_ONLY");
	});

	test("shows the selected root or merge commit with ordinary Git semantics", async () => {
		const fixture = createGitFixture();
		const h = createHarness();
		const commits = git(fixture.feature, "log", "--oneline", "-20").trim().split("\n");
		const rootEntry = commits.find((entry) => entry.startsWith(fixture.baseRevision.slice(0, 7)));
		const mergeEntry = commits.find((entry) => entry.startsWith(fixture.mergeRevision.slice(0, 7)));
		if (!rootEntry || !mergeEntry) throw new Error("fixture commits missing from picker range");

		await h.invoke(fixture.feature, "", { selections: ["Specific commit", rootEntry] });
		expect(runCommitReview(fixture.feature, h.sent[0]!)).toBe(
			git(fixture.feature, "show", "--format=fuller", "--patch", fixture.baseRevision, "--"),
		);
		await h.invoke(fixture.feature, "merge focus", { selections: ["Specific commit", mergeEntry] });
		expect(runCommitReview(fixture.feature, h.sent[1]!)).toBe(
			git(fixture.feature, "show", "--format=fuller", "--patch", fixture.mergeRevision, "--"),
		);
		expect(h.sent[1]).toContain("merge focus");
	});

	test("returns authoritative custom instructions inside or outside Git", async () => {
		const fixture = createGitFixture();
		const outsideGit = join(fixture.parent, "outside Git");
		mkdirSync(outsideGit);
		const instructions = "Review the branch against main.\nFocus on validation.";
		const h = createHarness();
		await h.invoke(outsideGit, "seed", {
			selections: ["Custom instructions"],
			editors: [instructions],
		});
		expect(h.sent[0]).toContain(instructions);

		const headlessPrompt = await h.invoke(outsideGit, instructions, { hasUI: false });
		expect(headlessPrompt).toContain(instructions);
		await h.invoke(outsideGit, "", { hasUI: false });
		expect(h.sent).toHaveLength(2);
		expect(h.notifications.at(-1)?.message).toContain("requires custom instructions");
	});

	test("cancels, rejects invalid scopes, and detects a changed origin", async () => {
		const fixture = createGitFixture();
		const h = createHarness();
		await h.invoke(fixture.feature, "", { selections: [undefined] });
		await h.invoke(fixture.feature, "", { selections: ["Custom instructions"], editors: ["  "] });
		await h.invoke(fixture.feature, "", {
			selections: ["Custom instructions"],
			editors: ["review this"],
			changeOriginAfterFirstSelection: true,
		});
		await h.invoke(fixture.feature, "", { selections: ["Specific commit", "not-a-revision missing"] });
		await h.invoke(fixture.feature, "", { selections: ["Against a base branch", "unrelated"] });
		await h.invoke(fixture.feature, "", { idle: false });

		expect(h.sent).toHaveLength(0);
		expect(h.notifications.some((notice) => notice.message.includes("active session or workspace changed"))).toBe(true);
		expect(h.notifications.some((notice) => notice.message.includes("did not resolve to a commit"))).toBe(true);
		expect(h.notifications.some((notice) => notice.message.includes("No common history"))).toBe(true);
		expect(h.notifications.some((notice) => notice.message.includes("active turn"))).toBe(true);
	});

	test("warns instead of widening empty repositories or single-branch history", async () => {
		const parent = mkdtempSync(join(tmpdir(), "omp-review-small-"));
		tempRoots.push(parent);
		const unborn = join(parent, "unborn");
		mkdirSync(unborn);
		git(unborn, "init", "-b", "main");
		const h = createHarness();
		await h.invoke(unborn, "", { selections: ["Specific commit"] });
		expect(h.sent).toHaveLength(0);

		git(unborn, "config", "user.name", "Basecamp Test");
		git(unborn, "config", "user.email", "basecamp@example.test");
		writeFileSync(join(unborn, "one.txt"), "one\n");
		commit(unborn, "one");
		await h.invoke(unborn, "", { selections: ["Against a base branch"] });
		expect(h.sent).toHaveLength(0);
		expect(h.notifications.some((notice) => notice.message.includes("No commits"))).toBe(true);
		expect(h.notifications.some((notice) => notice.message.includes("No alternative base branches"))).toBe(true);
	});
});
