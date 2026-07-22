import assert from "node:assert/strict";
import type { ChildProcess } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { DaemonPaths } from "../paths.ts";
import { PROTOCOL_VERSION } from "../protocol/index.ts";
import { ensureDaemon } from "../spawn.ts";

function fakeSpawn(): ChildProcess {
	return {
		unref() {
			// no-op
		},
	} as unknown as ChildProcess;
}

function daemonPaths(root: string, spawnLockPath = path.join(root, "daemon.spawn.lock")): DaemonPaths {
	return {
		runtimeDir: root,
		socketPath: path.join(root, "daemon.sock"),
		spawnLockPath,
		pidPath: path.join(root, "daemon.pid"),
		dbPath: path.join(root, "daemon.db"),
		agentsDir: path.join(root, "agents"),
	};
}

describe("ensureDaemon", () => {
	it("does not spawn when daemon is healthy with matching protocol", async () => {
		const root = fs.mkdtempSync(path.join(os.tmpdir(), "daemon-ensure-"));
		const calls: string[] = [];
		await ensureDaemon({
			resolvePathsFn: () => daemonPaths(root),
			healthPingFn: async () => ({ ok: true, protocol: PROTOCOL_VERSION }),
			spawnFn: () => {
				calls.push("spawn");
				return fakeSpawn();
			},
		});
		assert.equal(calls.length, 0);
	});

	it("terminates and restarts a healthy daemon with mismatched protocol", async () => {
		const root = fs.mkdtempSync(path.join(os.tmpdir(), "daemon-ensure-"));
		const paths = daemonPaths(root);
		const spawnArgs: string[][] = [];
		const killedSignals: NodeJS.Signals[] = [];
		const daemonPid = 4242;
		let daemonAlive = true;
		let healthCount = 0;

		await ensureDaemon({
			resolvePathsFn: () => paths,
			healthPingFn: async () => {
				healthCount += 1;
				if (healthCount < 3) return { ok: true, protocol: 999 };
				return { ok: true, protocol: PROTOCOL_VERSION };
			},
			findDaemonPidFn: async (socketPath) => {
				assert.equal(socketPath, paths.socketPath);
				return daemonPid;
			},
			pidExistsFn: (pid) => pid === daemonPid && daemonAlive,
			killPidFn: (pid, signal) => {
				assert.equal(pid, daemonPid);
				killedSignals.push(signal);
				daemonAlive = false;
			},
			spawnFn: (command, args) => {
				assert.equal(command, "basecamp");
				spawnArgs.push([...args]);
				return fakeSpawn();
			},
			sleepFn: async () => {},
		});

		assert.deepEqual(killedSignals, ["SIGTERM"]);
		assert.deepEqual(spawnArgs, [["hub", "--uds", paths.socketPath, "--pidfile", paths.pidPath, "--db", paths.dbPath]]);
	});

	it("throws if the restarted daemon is still protocol-incompatible", async () => {
		const root = fs.mkdtempSync(path.join(os.tmpdir(), "daemon-ensure-"));
		const paths = daemonPaths(root);
		const calls: string[] = [];

		await assert.rejects(
			ensureDaemon({
				resolvePathsFn: () => paths,
				healthPingFn: async () => ({ ok: true, protocol: 999 }),
				findDaemonPidFn: async () => null,
				spawnFn: () => {
					calls.push("spawn");
					return fakeSpawn();
				},
				sleepFn: async () => {},
			}),
			/protocol mismatch/,
		);
		assert.equal(calls.length, 1);
	});

	it("spawns once and polls until healthy", async () => {
		const root = fs.mkdtempSync(path.join(os.tmpdir(), "daemon-ensure-"));
		let healthCount = 0;
		const calls: string[] = [];
		await ensureDaemon({
			resolvePathsFn: () => daemonPaths(root),
			healthPingFn: async () => {
				healthCount += 1;
				if (healthCount < 3) return { ok: false };
				return { ok: true, protocol: PROTOCOL_VERSION };
			},
			spawnFn: () => {
				calls.push("spawn");
				return fakeSpawn();
			},
			sleepFn: async () => {},
		});
		assert.equal(calls.length, 1);
		assert.ok(healthCount >= 3);
	});

	it("reclaims stale spawn lock and starts daemon", async () => {
		const root = fs.mkdtempSync(path.join(os.tmpdir(), "daemon-ensure-"));
		const lockPath = path.join(root, "daemon.spawn.lock");
		fs.mkdirSync(root, { recursive: true });
		fs.writeFileSync(lockPath, JSON.stringify({ pid: 42424242, ts: Date.now() - 120_000 }));

		let healthCount = 0;
		const calls: string[] = [];
		await ensureDaemon({
			resolvePathsFn: () => daemonPaths(root, lockPath),
			healthPingFn: async () => {
				healthCount += 1;
				if (healthCount < 3) return { ok: false };
				return { ok: true, protocol: PROTOCOL_VERSION };
			},
			spawnFn: () => {
				calls.push("spawn");
				return fakeSpawn();
			},
			pidExistsFn: () => false,
			sleepFn: async () => {},
		});

		assert.equal(calls.length, 1);
		assert.equal(fs.existsSync(lockPath), false);
	});

	it("does not remove a spawn lock that replaced the acquired inode", async () => {
		const root = fs.mkdtempSync(path.join(os.tmpdir(), "daemon-ensure-"));
		const paths = daemonPaths(root);
		const replacement = JSON.stringify({ pid: 777, ts: Date.now() });
		let healthy = false;

		await ensureDaemon({
			resolvePathsFn: () => paths,
			healthPingFn: async () => (healthy ? { ok: true, protocol: PROTOCOL_VERSION } : { ok: false }),
			spawnFn: () => {
				fs.unlinkSync(paths.spawnLockPath);
				fs.writeFileSync(paths.spawnLockPath, replacement);
				healthy = true;
				return fakeSpawn();
			},
			sleepFn: async () => {},
		});

		assert.equal(fs.readFileSync(paths.spawnLockPath, "utf8"), replacement);
	});
});
