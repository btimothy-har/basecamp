import assert from "node:assert/strict";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { PullRequestStatus } from "../../git/pr-status.ts";
import { type RepositoryStatusOptions, RepositoryStatusTracker, type RepositoryTarget } from "../repository-status.ts";

interface Deferred<T> {
	promise: Promise<T>;
	resolve(value: T): void;
}

interface LookupCall {
	cwd: string;
	signal: AbortSignal | undefined;
}

interface TrackerHarness {
	tracker: RepositoryStatusTracker;
	lookupCalls: LookupCall[];
	watchers: Array<{
		listener: (event: string, filename: string | Buffer | null) => void;
		closed: boolean;
	}>;
	changes: number;
	intervalMs: number | null;
	intervalHandler: (() => void) | null;
	intervalUnrefed: boolean;
	intervalCleared: boolean;
	targetUnsubscribed: boolean;
	notifyTargetChange(): void;
}

function deferred<T>(): Deferred<T> {
	let resolvePromise: (value: T) => void = () => {};
	const promise = new Promise<T>((resolve) => {
		resolvePromise = resolve;
	});
	return { promise, resolve: resolvePromise };
}

function pullRequest(number: number, state: PullRequestStatus["state"] = "OPEN"): PullRequestStatus {
	return {
		number,
		url: `https://github.com/example/basecamp/pull/${number}`,
		state,
		isDraft: false,
	};
}

async function createCheckout(
	t: { after(fn: () => Promise<void> | void): void },
	branch: string,
	linked = false,
): Promise<{ directory: string; headPath: string }> {
	const root = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-repository-status-"));
	const directory = path.join(root, "checkout");
	await fs.mkdir(directory, { recursive: true });

	let headPath: string;
	if (linked) {
		const gitDirectory = path.join(root, "metadata");
		await fs.mkdir(gitDirectory, { recursive: true });
		await fs.writeFile(path.join(directory, ".git"), "gitdir: ../metadata\n");
		headPath = path.join(gitDirectory, "HEAD");
	} else {
		const gitDirectory = path.join(directory, ".git");
		await fs.mkdir(gitDirectory, { recursive: true });
		headPath = path.join(gitDirectory, "HEAD");
	}
	await fs.writeFile(headPath, `ref: refs/heads/${branch}\n`);

	t.after(() => fs.rm(root, { recursive: true, force: true }));
	return { directory, headPath };
}

function createHarness(
	targetRef: { current: RepositoryTarget },
	lookup: NonNullable<RepositoryStatusOptions["lookupPullRequest"]>,
): TrackerHarness {
	const lookupCalls: LookupCall[] = [];
	const watchers: TrackerHarness["watchers"] = [];
	let changes = 0;
	let targetListener: (() => void) | null = null;
	let intervalMs: number | null = null;
	let intervalHandler: (() => void) | null = null;
	let intervalUnrefed = false;
	let intervalCleared = false;
	let targetUnsubscribed = false;
	const timer = {
		unref() {
			intervalUnrefed = true;
		},
	} as unknown as ReturnType<typeof setInterval>;

	const tracker = new RepositoryStatusTracker(
		{} as ExtensionAPI,
		() => {
			changes += 1;
		},
		{
			getTarget: () => targetRef.current,
			subscribeTarget: (listener) => {
				targetListener = listener;
				return () => {
					targetUnsubscribed = true;
				};
			},
			lookupPullRequest: (_pi, cwd, signal) => {
				lookupCalls.push({ cwd, signal });
				return lookup(_pi, cwd, signal);
			},
			watchDirectory: (_directory, listener) => {
				const watcher = { listener, closed: false };
				watchers.push(watcher);
				return {
					close() {
						watcher.closed = true;
					},
				};
			},
			setIntervalFn: ((handler: () => void, ms: number) => {
				intervalHandler = handler;
				intervalMs = ms;
				return timer;
			}) as typeof setInterval,
			clearIntervalFn: ((value: ReturnType<typeof setInterval>) => {
				assert.equal(value, timer);
				intervalCleared = true;
			}) as typeof clearInterval,
		},
	);

	return {
		tracker,
		lookupCalls,
		watchers,
		get changes() {
			return changes;
		},
		get intervalMs() {
			return intervalMs;
		},
		get intervalHandler() {
			return intervalHandler;
		},
		get intervalUnrefed() {
			return intervalUnrefed;
		},
		get intervalCleared() {
			return intervalCleared;
		},
		get targetUnsubscribed() {
			return targetUnsubscribed;
		},
		notifyTargetChange() {
			targetListener?.();
		},
	};
}

async function settle(): Promise<void> {
	await new Promise<void>((resolve) => setImmediate(resolve));
}

describe("RepositoryStatusTracker", () => {
	it("loads the initial linked checkout and refreshes on demand and polling", async (t) => {
		const checkout = await createCheckout(t, "feature/footer", true);
		const results = [pullRequest(10), pullRequest(10), pullRequest(11, "MERGED"), pullRequest(12, "CLOSED")];
		const target = { current: { directory: checkout.directory, fallbackBranch: null } };
		const harness = createHarness(target, async () => results.shift() ?? null);

		await settle();
		assert.equal(harness.tracker.getBranch(), "feature/footer");
		assert.equal(harness.tracker.getPullRequest()?.number, 10);
		assert.equal(harness.lookupCalls[0]?.cwd, path.resolve(checkout.directory));
		assert.equal(harness.intervalMs, 5 * 60 * 1_000);
		assert.equal(harness.intervalUnrefed, true);

		const changesAfterInitialLoad = harness.changes;
		harness.tracker.refresh();
		await settle();
		assert.equal(harness.tracker.getPullRequest()?.number, 10);
		assert.equal(harness.changes, changesAfterInitialLoad);

		harness.tracker.refresh();
		await settle();
		assert.equal(harness.tracker.getPullRequest()?.number, 11);

		harness.intervalHandler?.();
		await settle();
		assert.equal(harness.tracker.getPullRequest()?.number, 12);
		harness.tracker.dispose();
	});

	it("retargets immediately for workspace and HEAD changes", async (t) => {
		const first = await createCheckout(t, "feature/one");
		const second = await createCheckout(t, "feature/two");
		const target = { current: { directory: first.directory, fallbackBranch: null } };
		const harness = createHarness(target, async (_pi, cwd) =>
			pullRequest(cwd === path.resolve(first.directory) ? 21 : 22),
		);

		await settle();
		assert.equal(harness.tracker.getPullRequest()?.number, 21);

		target.current = { directory: second.directory, fallbackBranch: null };
		harness.notifyTargetChange();
		assert.equal(harness.tracker.getBranch(), "feature/two");
		assert.equal(harness.tracker.getPullRequest(), null);
		assert.equal(harness.watchers[0]?.closed, true);
		await settle();
		assert.equal(harness.tracker.getPullRequest()?.number, 22);

		await fs.writeFile(second.headPath, "ref: refs/heads/feature/three\n");
		harness.watchers.at(-1)?.listener("change", "HEAD");
		assert.equal(harness.tracker.getBranch(), "feature/three");
		assert.equal(harness.tracker.getPullRequest(), null);
		await settle();
		assert.equal(harness.lookupCalls.length, 3);
		harness.tracker.dispose();
	});

	it("uses safe fallback branches and suppresses detached or unsafe HEAD values", async (t) => {
		const fallbackDirectory = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-repository-fallback-"));
		t.after(() => fs.rm(fallbackDirectory, { recursive: true, force: true }));
		const fallbackTarget = { current: { directory: fallbackDirectory, fallbackBranch: "feature/fallback" } };
		const fallback = createHarness(fallbackTarget, async () => pullRequest(30));
		await settle();
		assert.equal(fallback.tracker.getBranch(), "feature/fallback");
		assert.equal(fallback.tracker.getPullRequest()?.number, 30);
		fallback.tracker.dispose();

		const detachedCheckout = await createCheckout(t, "placeholder");
		await fs.writeFile(detachedCheckout.headPath, "0123456789abcdef\n");
		const detachedTarget = { current: { directory: detachedCheckout.directory, fallbackBranch: null } };
		const detached = createHarness(detachedTarget, async () => pullRequest(31));
		await settle();
		assert.equal(detached.tracker.getBranch(), "detached");
		assert.equal(detached.lookupCalls.length, 0);
		detached.tracker.dispose();

		const unsafeCheckout = await createCheckout(t, "placeholder");
		await fs.writeFile(unsafeCheckout.headPath, "ref: refs/heads/feature/\u001b]8;;unsafe\n");
		const unsafeTarget = { current: { directory: unsafeCheckout.directory, fallbackBranch: null } };
		const unsafe = createHarness(unsafeTarget, async () => pullRequest(32));
		await settle();
		assert.equal(unsafe.tracker.getBranch(), null);
		assert.equal(unsafe.lookupCalls.length, 0);
		unsafe.tracker.dispose();
	});

	it("discards late results from a previous checkout", async (t) => {
		const first = await createCheckout(t, "feature/one");
		const second = await createCheckout(t, "feature/two");
		const firstLookup = deferred<PullRequestStatus | null>();
		const secondLookup = deferred<PullRequestStatus | null>();
		const lookups = [firstLookup, secondLookup];
		const target = { current: { directory: first.directory, fallbackBranch: null } };
		const harness = createHarness(target, () => lookups.shift()!.promise);

		target.current = { directory: second.directory, fallbackBranch: null };
		harness.notifyTargetChange();
		assert.equal(harness.lookupCalls[0]?.signal?.aborted, true);
		secondLookup.resolve(pullRequest(32));
		await settle();
		assert.equal(harness.tracker.getPullRequest()?.number, 32);

		firstLookup.resolve(pullRequest(31));
		await settle();
		assert.equal(harness.tracker.getPullRequest()?.number, 32);
		harness.tracker.dispose();
	});

	it("retains same-target data and coalesces concurrent refreshes", async (t) => {
		const checkout = await createCheckout(t, "feature/footer");
		const initial = deferred<PullRequestStatus | null>();
		const failed = deferred<PullRequestStatus | null>();
		const pending = deferred<PullRequestStatus | null>();
		const lookups = [initial, failed, pending];
		const target = { current: { directory: checkout.directory, fallbackBranch: null } };
		const harness = createHarness(target, () => lookups.shift()!.promise);

		initial.resolve(pullRequest(40));
		await settle();
		assert.equal(harness.tracker.getPullRequest()?.number, 40);

		harness.tracker.refresh();
		harness.tracker.refresh();
		harness.tracker.refresh();
		assert.equal(harness.lookupCalls.length, 2);
		failed.resolve(null);
		await settle();
		assert.equal(harness.tracker.getPullRequest()?.number, 40);
		assert.equal(harness.lookupCalls.length, 3);

		pending.resolve(pullRequest(41));
		await settle();
		assert.equal(harness.tracker.getPullRequest()?.number, 41);
		harness.tracker.dispose();
	});

	it("cleans up subscriptions, watchers, polling, and in-flight work", async (t) => {
		const checkout = await createCheckout(t, "feature/footer");
		const inFlight = deferred<PullRequestStatus | null>();
		const target = { current: { directory: checkout.directory, fallbackBranch: null } };
		const harness = createHarness(target, () => inFlight.promise);
		const changesBeforeDispose = harness.changes;

		harness.tracker.dispose();
		assert.equal(harness.targetUnsubscribed, true);
		assert.equal(harness.intervalCleared, true);
		assert.equal(harness.watchers[0]?.closed, true);
		assert.equal(harness.lookupCalls[0]?.signal?.aborted, true);
		assert.equal(harness.tracker.getBranch(), null);
		assert.equal(harness.tracker.getPullRequest(), null);

		harness.notifyTargetChange();
		harness.intervalHandler?.();
		inFlight.resolve(pullRequest(50));
		await settle();
		assert.equal(harness.lookupCalls.length, 1);
		assert.equal(harness.changes, changesBeforeDispose);
	});
});
