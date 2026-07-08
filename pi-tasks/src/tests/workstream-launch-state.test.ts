import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, it } from "node:test";
import {
	appendWorkstreamLaunchRecord,
	appendWorkstreamLaunchRecordIfAbsent,
	buildWorkstreamLaunchFingerprint,
	defaultWorkstreamLaunchesDir,
	emptyWorkstreamLaunchState,
	findDuplicateWorkstreamLaunch,
	findWorkstreamLaunchById,
	listWorkstreamLaunchRecords,
	loadWorkstreamLaunchState,
	saveWorkstreamLaunchState,
	stampWorkstreamLaunchAgentHandle,
	updateFailedWorkstreamLaunchRecord,
	updateWorkstreamLaunchRecord,
	type WorkstreamLaunchRecord,
	workstreamLaunchStatePath,
} from "../workstreams/launch-state.ts";

const tmpDirs: string[] = [];

function makeTmpDir(): string {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-workstream-launch-state-"));
	tmpDirs.push(dir);
	return dir;
}

afterEach(() => {
	for (const dir of tmpDirs.splice(0)) {
		fs.rmSync(dir, { recursive: true, force: true });
	}
});

function makeRecord(overrides: Partial<WorkstreamLaunchRecord> = {}): WorkstreamLaunchRecord {
	const id = overrides.id ?? "launch-1";
	return {
		id,
		fingerprint: "fingerprint-1",
		repo: "org/repo",
		source: {
			dossierPath: "/repo/logseq/pages/dossier.md",
			repoPagePath: "/repo/logseq/pages/repo.md",
			...overrides.source,
		},
		workstream: {
			label: "workstream-one",
			brief: "Implement the first workstream.",
			constraints: "Stay focused.",
			...overrides.workstream,
		},
		worktree: {
			label: "bt/workstream-one",
			path: "/worktrees/org/repo/bt/workstream-one",
			branch: "bt/workstream-one",
			created: true,
			...overrides.worktree,
		},
		agent: {
			handle: "agent-1",
			type: "worker",
			...overrides.agent,
		},
		setup: {
			status: "pending",
			...overrides.setup,
		},
		herdr: {
			status: "pending",
			...overrides.herdr,
		},
		launch: {
			status: "pending",
			...overrides.launch,
		},
		createdAt: "2026-07-03T00:00:00.000Z",
		updatedAt: "2026-07-03T00:00:00.000Z",
		...overrides,
	};
}

function readJson(filePath: string): unknown {
	return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

describe("workstream launch path helpers", () => {
	it("builds launch-index paths under the Basecamp workstream-launches directory", () => {
		const homeDir = path.join("tmp", "home");
		const launchesDir = path.join(homeDir, ".pi", "basecamp", "workstream-launches");

		assert.equal(defaultWorkstreamLaunchesDir(homeDir), launchesDir);
		assert.equal(workstreamLaunchStatePath(launchesDir), path.join(launchesDir, "launch-index.json"));
	});
});

describe("buildWorkstreamLaunchFingerprint", () => {
	it("builds a stable fingerprint from repo, dossier path, and label", () => {
		const first = buildWorkstreamLaunchFingerprint({
			repo: "Org/Repo",
			dossierPath: "/repo/logseq/pages/../pages/dossier.md",
			label: " Workstream   One ",
		});
		const second = buildWorkstreamLaunchFingerprint({
			repo: "org/repo",
			dossierPath: "/repo/logseq/pages/dossier.md",
			label: "workstream one",
		});

		assert.equal(first, second);
		assert.match(first, /^wlfp_[a-f0-9]{16}$/);
	});

	it("distinguishes different dossiers and labels", () => {
		const base = buildWorkstreamLaunchFingerprint({
			repo: "org/repo",
			dossierPath: "/repo/logseq/pages/dossier.md",
			label: "workstream one",
		});

		assert.notEqual(
			base,
			buildWorkstreamLaunchFingerprint({
				repo: "org/repo",
				dossierPath: "/repo/logseq/pages/other.md",
				label: "workstream one",
			}),
		);
		assert.notEqual(
			base,
			buildWorkstreamLaunchFingerprint({
				repo: "org/repo",
				dossierPath: "/repo/logseq/pages/dossier.md",
				label: "workstream two",
			}),
		);
	});
});

describe("loadWorkstreamLaunchState", () => {
	it("returns empty versioned state for missing files", () => {
		const filePath = path.join(makeTmpDir(), "missing", "launch-index.json");

		assert.deepEqual(loadWorkstreamLaunchState(filePath), emptyWorkstreamLaunchState());
	});

	it("returns empty versioned state for malformed JSON", () => {
		const filePath = path.join(makeTmpDir(), "launch-index.json");
		fs.writeFileSync(filePath, "not json");

		assert.deepEqual(loadWorkstreamLaunchState(filePath), emptyWorkstreamLaunchState());
	});

	it("returns empty versioned state for non-object and invalid object payloads", () => {
		const dir = makeTmpDir();
		const filePath = path.join(dir, "launch-index.json");

		fs.writeFileSync(filePath, JSON.stringify([]));
		assert.deepEqual(loadWorkstreamLaunchState(filePath), emptyWorkstreamLaunchState());

		fs.writeFileSync(filePath, JSON.stringify({ version: 1, records: "nope" }));
		assert.deepEqual(loadWorkstreamLaunchState(filePath), emptyWorkstreamLaunchState());
	});
});

describe("workstream launch persistence", () => {
	it("saves atomically via a temp file and rename", () => {
		const filePath = path.join(makeTmpDir(), "nested", "launch-index.json");
		const record = makeRecord();

		saveWorkstreamLaunchState(filePath, { version: 1, records: [record] });

		assert.deepEqual(readJson(filePath), { version: 1, records: [record] });
		assert.equal(fs.existsSync(`${filePath}.tmp`), false);
	});

	it("appends records and updates records in place", () => {
		const filePath = path.join(makeTmpDir(), "launch-index.json");
		const first = makeRecord();
		const second = makeRecord({ id: "launch-2", fingerprint: "fingerprint-2", worktree: { label: "bt/second" } });

		const appendedFirst = appendWorkstreamLaunchRecord(filePath, first);
		const appendedSecond = appendWorkstreamLaunchRecord(filePath, second);
		const updated = updateWorkstreamLaunchRecord(
			filePath,
			"launch-1",
			{
				worktree: { path: "/new/path", branch: "bt/new", created: false },
				agent: { handle: "agent-2" },
				setup: { status: "succeeded", message: "setup complete" },
				launch: { status: "failed", error: "agent unavailable" },
			},
			"2026-07-03T01:00:00.000Z",
		);

		assert.equal(appendedFirst.records.length, 1);
		assert.equal(appendedSecond.records.length, 2);
		assert.equal(updated?.createdAt, first.createdAt);
		assert.equal(updated?.updatedAt, "2026-07-03T01:00:00.000Z");
		assert.deepEqual(updated?.worktree, {
			label: first.worktree.label,
			path: "/new/path",
			branch: "bt/new",
			created: false,
		});
		assert.deepEqual(updated?.agent, { handle: "agent-2", type: "worker" });
		assert.deepEqual(updated?.setup, { status: "succeeded", message: "setup complete" });
		assert.deepEqual(updated?.launch, { status: "failed", error: "agent unavailable" });
		assert.equal(fs.existsSync(`${filePath}.tmp`), false);

		const persisted = loadWorkstreamLaunchState(filePath);
		assert.equal(persisted.records.length, 2);
		assert.equal(persisted.records[0]?.id, "launch-1");
		assert.equal(persisted.records[1]?.id, "launch-2");
		assert.equal(persisted.records[0]?.updatedAt, "2026-07-03T01:00:00.000Z");
	});

	it("replaces operation state instead of carrying stale messages forward", () => {
		const filePath = path.join(makeTmpDir(), "launch-index.json");
		appendWorkstreamLaunchRecord(
			filePath,
			makeRecord({ setup: { status: "succeeded", message: "setup complete", error: "old error" } }),
		);

		const updated = updateWorkstreamLaunchRecord(filePath, "launch-1", { setup: { status: "running" } });

		assert.deepEqual(updated?.setup, { status: "running" });
	});

	it("appends only when no matching launch identity exists at the write boundary", () => {
		const filePath = path.join(makeTmpDir(), "launch-index.json");
		const first = makeRecord();
		const duplicate = makeRecord({ id: "launch-2", worktree: { label: "bt/second" } });

		const appended = appendWorkstreamLaunchRecordIfAbsent(filePath, first, {
			fingerprint: first.fingerprint,
			worktreeLabel: first.worktree.label,
		});
		const skipped = appendWorkstreamLaunchRecordIfAbsent(filePath, duplicate, {
			fingerprint: first.fingerprint,
			worktreeLabel: duplicate.worktree.label,
		});

		assert.equal(appended.appended, true);
		assert.equal(skipped.appended, false);
		assert.equal(skipped.record.id, "launch-1");
		assert.deepEqual(
			loadWorkstreamLaunchState(filePath).records.map((record) => record.id),
			["launch-1"],
		);
	});

	it("rejects duplicate launch ids in the same repo at the write boundary", () => {
		const filePath = path.join(makeTmpDir(), "launch-index.json");
		const first = makeRecord({ id: "launch-workstream-too", repo: "org/repo" });
		const sameRepoDuplicateId = makeRecord({
			id: "launch-workstream-too",
			fingerprint: "fingerprint-2",
			repo: "org/repo",
			worktree: { label: "bt/second" },
		});
		const otherRepoSameId = makeRecord({
			id: "launch-workstream-too",
			fingerprint: "fingerprint-3",
			repo: "org/other",
			worktree: { label: "bt/other" },
		});

		const appended = appendWorkstreamLaunchRecordIfAbsent(filePath, first, {
			repo: first.repo,
			fingerprint: first.fingerprint,
			worktreeLabel: first.worktree.label,
		});
		const skipped = appendWorkstreamLaunchRecordIfAbsent(filePath, sameRepoDuplicateId, {
			repo: sameRepoDuplicateId.repo,
			fingerprint: sameRepoDuplicateId.fingerprint,
			worktreeLabel: sameRepoDuplicateId.worktree.label,
		});
		const otherRepoAppended = appendWorkstreamLaunchRecordIfAbsent(filePath, otherRepoSameId, {
			repo: otherRepoSameId.repo,
			fingerprint: otherRepoSameId.fingerprint,
			worktreeLabel: otherRepoSameId.worktree.label,
		});

		assert.equal(appended.appended, true);
		assert.equal(skipped.appended, false);
		assert.equal(skipped.record.fingerprint, "fingerprint-1");
		assert.equal(otherRepoAppended.appended, true);
		assert.deepEqual(
			loadWorkstreamLaunchState(filePath).records.map((record) => `${record.repo}:${record.id}`),
			["org/repo:launch-workstream-too", "org/other:launch-workstream-too"],
		);
	});

	it("only updates failed launch records when reclaiming a tombstone", () => {
		const filePath = path.join(makeTmpDir(), "launch-index.json");
		appendWorkstreamLaunchRecord(filePath, makeRecord({ launch: { status: "failed", error: "old failure" } }));

		const reclaimed = updateFailedWorkstreamLaunchRecord(
			filePath,
			"launch-1",
			{ launch: { status: "running", message: "retrying" } },
			"2026-07-03T01:00:00.000Z",
		);
		const skipped = updateFailedWorkstreamLaunchRecord(
			filePath,
			"launch-1",
			{ launch: { status: "running", message: "retrying again" } },
			"2026-07-03T02:00:00.000Z",
		);

		assert.equal(reclaimed?.launch.status, "running");
		assert.equal(reclaimed?.updatedAt, "2026-07-03T01:00:00.000Z");
		assert.equal(skipped, null);
		assert.equal(loadWorkstreamLaunchState(filePath).records[0]?.updatedAt, "2026-07-03T01:00:00.000Z");
	});

	it("returns null when updating an unknown record", () => {
		const filePath = path.join(makeTmpDir(), "launch-index.json");
		appendWorkstreamLaunchRecord(filePath, makeRecord());

		assert.equal(updateWorkstreamLaunchRecord(filePath, "missing", { launch: { status: "running" } }), null);
	});
});

describe("workstream launch id model", () => {
	it("finds a record by id scoped to the repo", () => {
		const filePath = path.join(makeTmpDir(), "launch-index.json");
		appendWorkstreamLaunchRecord(filePath, makeRecord({ id: "launch-workstream-too", repo: "org/repo" }));

		assert.equal(findWorkstreamLaunchById(filePath, "launch-workstream-too")?.id, "launch-workstream-too");
		assert.equal(findWorkstreamLaunchById(filePath, "launch-workstream-too", "org/repo")?.repo, "org/repo");
		assert.equal(findWorkstreamLaunchById(filePath, "launch-workstream-too", "org/other"), null);
		assert.equal(findWorkstreamLaunchById(filePath, "missing"), null);
	});

	it("stamps an agent handle onto an existing record by id without a prior handle", () => {
		const filePath = path.join(makeTmpDir(), "launch-index.json");
		appendWorkstreamLaunchRecord(filePath, makeRecord({ id: "launch-workstream-too", agent: {} }));

		assert.equal(findWorkstreamLaunchById(filePath, "launch-workstream-too")?.agent.handle, undefined);
		const stamped = stampWorkstreamLaunchAgentHandle(filePath, "launch-workstream-too", "swift-otter-1a2b3c");
		assert.equal(stamped?.agent.handle, "swift-otter-1a2b3c");
		assert.equal(findWorkstreamLaunchById(filePath, "launch-workstream-too")?.agent.handle, "swift-otter-1a2b3c");
		assert.equal(stampWorkstreamLaunchAgentHandle(filePath, "missing", "x"), null);
	});
});

describe("workstream launch queries", () => {
	it("lists records filtered by repo and dossier path", () => {
		const filePath = path.join(makeTmpDir(), "launch-index.json");
		appendWorkstreamLaunchRecord(filePath, makeRecord({ id: "launch-1" }));
		appendWorkstreamLaunchRecord(
			filePath,
			makeRecord({
				id: "launch-2",
				fingerprint: "fingerprint-2",
				repo: "org/repo",
				source: { dossierPath: "/repo/logseq/pages/other.md" },
				worktree: { label: "bt/other" },
			}),
		);
		appendWorkstreamLaunchRecord(
			filePath,
			makeRecord({
				id: "launch-3",
				fingerprint: "fingerprint-3",
				repo: "org/other",
				source: { dossierPath: "/other/logseq/pages/dossier.md" },
				worktree: { label: "bt/third" },
			}),
		);

		assert.deepEqual(
			listWorkstreamLaunchRecords(filePath, { repo: "org/repo" }).map((record) => record.id),
			["launch-1", "launch-2"],
		);
		assert.deepEqual(
			listWorkstreamLaunchRecords(filePath, { dossierPath: "/repo/logseq/pages/dossier.md" }).map(
				(record) => record.id,
			),
			["launch-1"],
		);
		assert.deepEqual(
			listWorkstreamLaunchRecords(filePath, {
				repo: "org/repo",
				dossierPath: "/repo/logseq/pages/other.md",
			}).map((record) => record.id),
			["launch-2"],
		);
	});

	it("finds duplicates by fingerprint or worktree label", () => {
		const filePath = path.join(makeTmpDir(), "launch-index.json");
		appendWorkstreamLaunchRecord(filePath, makeRecord());
		appendWorkstreamLaunchRecord(
			filePath,
			makeRecord({ id: "launch-2", fingerprint: "fingerprint-2", worktree: { label: "bt/second" } }),
		);

		assert.equal(findDuplicateWorkstreamLaunch(filePath, { fingerprint: "fingerprint-2" })?.id, "launch-2");
		assert.equal(findDuplicateWorkstreamLaunch(filePath, { worktreeLabel: "bt/workstream-one" })?.id, "launch-1");
		assert.equal(
			findDuplicateWorkstreamLaunch(filePath, { fingerprint: "fingerprint-2", worktreeLabel: "bt/workstream-one" })?.id,
			"launch-1",
		);
		assert.equal(findDuplicateWorkstreamLaunch(filePath, { fingerprint: "missing" }), null);
		assert.equal(findDuplicateWorkstreamLaunch(filePath, {}), null);
	});

	it("does not treat a matching worktree label in another repo as a duplicate", () => {
		const filePath = path.join(makeTmpDir(), "launch-index.json");
		appendWorkstreamLaunchRecord(filePath, makeRecord({ repo: "org/other", worktree: { label: "bt/shared" } }));

		// Scoped lookup: same worktree label in a different repo must not match.
		assert.equal(findDuplicateWorkstreamLaunch(filePath, { repo: "org/repo", worktreeLabel: "bt/shared" }), null);

		// And appending for the target repo is not blocked by the other repo's record.
		const appended = appendWorkstreamLaunchRecordIfAbsent(
			filePath,
			makeRecord({ id: "launch-2", fingerprint: "fingerprint-2", repo: "org/repo", worktree: { label: "bt/shared" } }),
			{ fingerprint: "fingerprint-2", worktreeLabel: "bt/shared" },
		);
		assert.equal(appended.appended, true);
		assert.equal(appended.record.id, "launch-2");
	});
});

describe("workstream launch records", () => {
	it("do not persist durable workstream state fields", () => {
		const filePath = path.join(makeTmpDir(), "launch-index.json");
		appendWorkstreamLaunchRecord(filePath, {
			...makeRecord(),
			priority: "high",
			blockers: ["blocked"],
			decisions: ["decided"],
			done: true,
			status: "active",
			workstream: {
				...makeRecord().workstream,
				priority: "high",
				blockers: ["blocked"],
				decisions: ["decided"],
				done: true,
				status: "active",
			},
		} as unknown as WorkstreamLaunchRecord);

		const persisted = JSON.stringify(readJson(filePath));
		assert.equal(persisted.includes("priority"), false);
		assert.equal(persisted.includes("blockers"), false);
		assert.equal(persisted.includes("decisions"), false);
		assert.equal(persisted.includes("done"), false);
		assert.equal(persisted.includes('"status":"active"'), false);
	});
});
