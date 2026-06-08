import assert from "node:assert/strict";
import type { ChildProcess } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import { ensureDaemon } from "../agents/daemon/client.ts";
import { PROTOCOL_VERSION } from "../agents/daemon/frames.ts";

function fakeSpawn(): ChildProcess {
	return {
		unref() {
			// no-op
		},
	} as unknown as ChildProcess;
}

describe("ensureDaemon", () => {
	it("does not spawn when daemon is healthy with matching protocol", async () => {
		const root = fs.mkdtempSync(path.join(os.tmpdir(), "daemon-ensure-"));
		const calls: string[] = [];
		await ensureDaemon({
			resolvePathsFn: () => ({
				runtimeDir: root,
				socketPath: path.join(root, "daemon.sock"),
				spawnLockPath: path.join(root, "daemon.spawn.lock"),
			}),
			healthPingFn: async () => ({ ok: true, protocol: PROTOCOL_VERSION }),
			spawnFn: () => {
				calls.push("spawn");
				return fakeSpawn();
			},
		});
		assert.equal(calls.length, 0);
	});

	it("throws on healthy protocol mismatch without spawning", async () => {
		const root = fs.mkdtempSync(path.join(os.tmpdir(), "daemon-ensure-"));
		const calls: string[] = [];
		await assert.rejects(
			ensureDaemon({
				resolvePathsFn: () => ({
					runtimeDir: root,
					socketPath: path.join(root, "daemon.sock"),
					spawnLockPath: path.join(root, "daemon.spawn.lock"),
				}),
				healthPingFn: async () => ({ ok: true, protocol: 999 }),
				spawnFn: () => {
					calls.push("spawn");
					return fakeSpawn();
				},
			}),
			/protocol mismatch/,
		);
		assert.equal(calls.length, 0);
	});

	it("spawns once and polls until healthy", async () => {
		const root = fs.mkdtempSync(path.join(os.tmpdir(), "daemon-ensure-"));
		let healthCount = 0;
		const calls: string[] = [];
		await ensureDaemon({
			resolvePathsFn: () => ({
				runtimeDir: root,
				socketPath: path.join(root, "daemon.sock"),
				spawnLockPath: path.join(root, "daemon.spawn.lock"),
			}),
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
			resolvePathsFn: () => ({
				runtimeDir: root,
				socketPath: path.join(root, "daemon.sock"),
				spawnLockPath: lockPath,
			}),
			healthPingFn: async () => {
				healthCount += 1;
				if (healthCount < 2) return { ok: false };
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
});
