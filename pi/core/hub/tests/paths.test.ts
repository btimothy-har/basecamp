import assert from "node:assert/strict";
import * as path from "node:path";
import { describe, it } from "node:test";
import { resolveDaemonPaths } from "../paths.ts";

describe("daemon paths", () => {
	it("resolves runtime, socket, lock, database, and agent paths under ~/.pi/basecamp/swarm", () => {
		const fakeHome = path.join(path.sep, "tmp", "fake-home");
		const runtimeDir = path.join(fakeHome, ".pi", "basecamp", "swarm");
		const paths = resolveDaemonPaths(fakeHome);
		assert.equal(paths.runtimeDir, runtimeDir);
		assert.equal(paths.socketPath, path.join(runtimeDir, "daemon.sock"));
		assert.equal(paths.spawnLockPath, path.join(runtimeDir, "daemon.spawn.lock"));
		assert.equal(paths.pidPath, path.join(runtimeDir, "daemon.pid"));
		assert.equal(paths.dbPath, path.join(runtimeDir, "daemon.db"));
		assert.equal(paths.agentsDir, path.join(runtimeDir, "agents"));
	});
});
